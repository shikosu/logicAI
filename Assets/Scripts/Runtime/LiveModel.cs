using System;
using System.Collections.Generic;
using System.Globalization;

namespace LogicAI
{
    // Ce que l'on regarde : l'essai en direct, ou la rediffusion d'une découverte.
    public enum LiveView
    {
        Direct,
        Replay,
    }

    // La logique de l'affichage en direct, sans dessin ni réseau (donc testable seule) :
    // elle reçoit les messages déjà lus par LiveMessageParser et dit quoi dessiner.
    // Unity ne calcule rien du circuit : il garde ce que Python envoie et rejoue l'ordre de pose.
    //
    //   messages --Apply--> [ LiveModel ] --Shown, Version--> CircuitViewer (dessine)
    //   horloge  --Advance->
    //
    // Les durées sont passées en paramètre (Advance) : pas d'horloge cachée, tests déterministes.
    public class LiveModel
    {
        // Valeur de départ, à régler par essais : une pièce posée toutes les 0,4 s.
        public const float ReplayStepSeconds = 0.4f;

        readonly List<DiscoveryData> discoveries = new List<DiscoveryData>();
        CircuitFile liveCircuit;
        StateData liveState;
        CircuitFile shown;
        DiscoveryData replayed;
        float stepClock;

        // La bibliothèque : les découvertes reçues, dans l'ordre d'arrivée.
        public IReadOnlyList<DiscoveryData> Discoveries { get { return discoveries; } }

        // Les dernières statistiques (nulles tant que Python n'en a pas envoyé).
        public StatsData Stats { get; private set; }

        // Le nombre d'images « etat » écartées (pas de circuit, ou taille qui ne correspond pas).
        public int IgnoredFrames { get; private set; }

        public LiveView View { get; private set; }

        // La découverte rediffusée (nulle en vue directe).
        public DiscoveryData Replayed { get { return replayed; } }

        // Le nombre de pièces (nœuds et câbles) déjà posées dans la rediffusion, sur le total.
        public int ReplayStep { get; private set; }

        public int ReplayStepCount
        {
            get { return replayed == null || replayed.ordre_de_pose == null ? 0 : replayed.ordre_de_pose.Length; }
        }

        public bool IsPlaying { get; private set; }

        // Le circuit à dessiner maintenant (nul = rien à dessiner).
        public CircuitFile Shown { get { return shown; } }

        // Augmente chaque fois que Shown est remplacé : le viewer ne redessine que dans ce cas.
        public int Version { get; private set; }

        // Le circuit sur lequel cadrer la caméra : en rediffusion, le circuit complet de la
        // découverte (la vue ne saute pas à chaque pièce posée).
        public CircuitFile FitTarget
        {
            get { return View == LiveView.Replay ? replayed.circuit : liveCircuit; }
        }

        // Le texte au-dessus du dessin.
        public string Caption
        {
            get
            {
                if (View == LiveView.Replay)
                {
                    return DiscoveryLabel(replayed) + " - étape " + ReplayStep + "/" + ReplayStepCount;
                }
                if (liveCircuit == null)
                {
                    return "en attente d'un essai...";
                }
                if (liveState == null)
                {
                    return "essai en direct (en attente des valeurs)";
                }
                string stability = liveState.stable ? "stable" : "INSTABLE";
                return "essai en direct - top " + liveState.top + " - " + stability;
            }
        }

        // Le texte du panneau de statistiques.
        public string StatsText
        {
            get
            {
                if (Stats == null)
                {
                    return "en attente de statistiques";
                }
                string plural = Stats.decouvertes > 1 ? "s" : "";
                return "Palier " + Stats.palier + " - génération " + Stats.generation
                    + " - " + Stats.decouvertes + " découverte" + plural
                    + " - récompense moyenne " + Stats.recompense_moyenne.ToString("0.00", CultureInfo.InvariantCulture);
            }
        }

        // Le texte d'une ligne de la bibliothèque : « NOT - nouveauté - 1 NAND ».
        public static string DiscoveryLabel(DiscoveryData discovery)
        {
            string genre = discovery.genre == LiveMessageParser.NewGenre ? "nouveauté" : discovery.genre;
            return discovery.nom + " - " + genre + " - " + discovery.cout + " NAND";
        }

        // --- Les messages reçus --------------------------------------------------------

        public void Apply(LiveMessage message)
        {
            if (message == null)
            {
                throw new ArgumentNullException("message");
            }
            switch (message.Kind)
            {
                case LiveMessageKind.Circuit:
                    ApplyCircuit(message.Circuit);
                    break;
                case LiveMessageKind.State:
                    ApplyState(message.State);
                    break;
                case LiveMessageKind.Discovery:
                    ApplyDiscovery(message.Discovery);
                    break;
                case LiveMessageKind.Stats:
                    Stats = message.Stats;
                    break;
            }
        }

        // Efface tout : à appeler quand on se reconnecte à Python (il renvoie alors tout l'historique).
        public void Reset()
        {
            discoveries.Clear();
            liveCircuit = null;
            liveState = null;
            Stats = null;
            IgnoredFrames = 0;
            replayed = null;
            View = LiveView.Direct;
            IsPlaying = false;
            stepClock = 0f;
            Show(null);
        }

        // Un nouveau circuit remplace l'ancien et ses valeurs (sinon elles colorieraient le nouveau).
        void ApplyCircuit(CircuitFile circuit)
        {
            liveCircuit = circuit;
            liveState = null;
            if (View == LiveView.Direct)
            {
                Show(DirectCircuit());
            }
        }

        // Une image de valeurs n'est montrée que si elle correspond au circuit courant. Le serveur
        // peut jeter un « circuit » en gardant ses « etat » : une image peut arriver sans son circuit.
        void ApplyState(StateData state)
        {
            if (liveCircuit == null || state == null || state.noeuds == null || state.cables == null)
            {
                IgnoredFrames++;
                return;
            }
            var candidate = new CircuitFile { nom = liveCircuit.nom, noeuds = liveCircuit.noeuds, cables = liveCircuit.cables, etat = state };
            try
            {
                CircuitLoader.Validate(candidate);
            }
            catch (CircuitFormatException)
            {
                IgnoredFrames++;
                return;
            }
            liveState = state;
            if (View == LiveView.Direct)
            {
                Show(DirectCircuit());
            }
        }

        // Une découverte déjà connue (même nom, genre et coût) est remplacée sur place : après une
        // reconnexion, Python renvoie l'historique et la bibliothèque ne doit pas avoir de doublons.
        void ApplyDiscovery(DiscoveryData discovery)
        {
            for (int index = 0; index < discoveries.Count; index++)
            {
                DiscoveryData known = discoveries[index];
                if (known.nom == discovery.nom && known.genre == discovery.genre && known.cout == discovery.cout)
                {
                    discoveries[index] = discovery;
                    return;
                }
            }
            discoveries.Add(discovery);
        }

        CircuitFile DirectCircuit()
        {
            if (liveCircuit == null)
            {
                return null;
            }
            if (liveState == null)
            {
                return liveCircuit;
            }
            return new CircuitFile { nom = liveCircuit.nom, noeuds = liveCircuit.noeuds, cables = liveCircuit.cables, etat = liveState };
        }

        void Show(CircuitFile file)
        {
            if (file == null && shown == null)
            {
                return;
            }
            shown = file;
            Version++;
        }

        // --- La rediffusion --------------------------------------------------------------

        // Rejoue la découverte numéro « index » de la bibliothèque, depuis le début. Faux si le numéro est invalide.
        // La découverte est mémorisée : la remplacer dans la bibliothèque ne perturbe pas la rediffusion en cours.
        public bool StartReplay(int index)
        {
            if (index < 0 || index >= discoveries.Count)
            {
                return false;
            }
            replayed = discoveries[index];
            View = LiveView.Replay;
            Restart();
            return true;
        }

        public void ReturnToDirect()
        {
            if (View == LiveView.Direct)
            {
                return;
            }
            replayed = null;
            View = LiveView.Direct;
            IsPlaying = false;
            Show(DirectCircuit());
        }

        // Recommence la rediffusion à zéro, en lecture.
        public void Restart()
        {
            if (View != LiveView.Replay)
            {
                return;
            }
            ReplayStep = 0;
            stepClock = 0f;
            IsPlaying = ReplayStepCount > 0;
            ShowReplay();
        }

        // Fait avancer la lecture de « seconds » secondes (une pièce toutes les ReplayStepSeconds).
        public void Advance(float seconds)
        {
            if (View != LiveView.Replay || !IsPlaying || seconds <= 0f)
            {
                return;
            }
            int before = ReplayStep;
            stepClock += seconds;
            while (stepClock >= ReplayStepSeconds && ReplayStep < ReplayStepCount)
            {
                stepClock -= ReplayStepSeconds;
                ReplayStep++;
            }
            if (ReplayStep >= ReplayStepCount)
            {
                IsPlaying = false;
                stepClock = 0f;
            }
            if (ReplayStep != before)
            {
                ShowReplay();
            }
        }

        // Pas à pas : met la lecture en pause, puis avance ou recule d'une pièce.
        public void StepForward()
        {
            if (View != LiveView.Replay)
            {
                return;
            }
            IsPlaying = false;
            if (ReplayStep < ReplayStepCount)
            {
                ReplayStep++;
                ShowReplay();
            }
        }

        public void StepBack()
        {
            if (View != LiveView.Replay)
            {
                return;
            }
            IsPlaying = false;
            if (ReplayStep > 0)
            {
                ReplayStep--;
                ShowReplay();
            }
        }

        // Pause / lecture. Relancer la lecture à la fin recommence depuis le début.
        public void TogglePause()
        {
            if (View != LiveView.Replay)
            {
                return;
            }
            if (IsPlaying)
            {
                IsPlaying = false;
            }
            else if (ReplayStep >= ReplayStepCount)
            {
                Restart();
            }
            else
            {
                IsPlaying = true;
            }
        }

        // Les « ReplayStep » premières étapes de la découverte ; rien tant que rien n'est posé.
        void ShowReplay()
        {
            if (ReplayStep == 0)
            {
                Show(null);
                return;
            }
            Show(LivePlacement.BuildCircuit(replayed.nom, replayed.ordre_de_pose, ReplayStep));
        }
    }
}
