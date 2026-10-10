using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace LogicAI
{
    // Ce que le visualiseur montre : les fichiers du dossier circuits/ (phase 3), ou le direct de
    // Python (phase 5).
    public enum ViewerMode
    {
        Files,
        Live,
    }

    // Le visualiseur. Au lancement du mode Play, il lit les fichiers du dossier circuits/ (à la
    // racine du projet), affiche une liste cliquable et dessine le circuit choisi (mode Files).
    // Le bouton « En direct » le connecte à Python (python -m logicai.live) : il montre alors l'essai
    // en cours, la bibliothèque des découvertes et leur rediffusion (mode Live).
    //
    // Il démarre tout seul (RuntimeInitializeOnLoadMethod) : aucune modification de la scène
    // n'est nécessaire. Il démarre toujours en mode Files, sans connexion : se connecter au
    // démarrage volerait la liaison d'un autre Unity (Python n'accepte qu'un client à la fois).
    public class CircuitViewer : MonoBehaviour
    {
        // Le dossier lu. Vide = le dossier circuits/ à la racine du projet.
        public string folder = "";

        // Le port où Python écoute (python -m logicai.live, 8765 par défaut).
        public int port = LiveConnection.DefaultPort;

        // La largeur, en pixels, de la liste à gauche : la caméra ne dessine pas dessous.
        const float PanelWidth = 240f;
        const float Margin = 1.2f;

        // Garde-fous : au plus 2000 lignes lues par image (le reste attend l'image suivante), et une
        // image trop longue (fenêtre en pause...) ne fait pas sauter la rediffusion.
        const int MaxLinesPerFrame = 2000;
        const float MaxFrameSeconds = 1f;

        readonly List<string> files = new List<string>();
        readonly LiveModel live = new LiveModel();
        GameObject drawn;
        int selected = -1;
        int lastScreenWidth;
        Vector2 scroll;

        LiveConnection connection;
        int lineConnection;
        int drawnVersion = -1;
        CircuitFile fitted;

        // Une action demandée par un bouton : exécutée dans Update, jamais pendant OnGUI. Changer le
        // nombre de boutons pendant un OnGUI fait échouer la mise en page d'IMGUI.
        Action pendingAction;

        public IReadOnlyList<string> Files { get { return files; } }
        public CircuitFile Current { get; private set; }
        public string ErrorMessage { get; private set; }

        public ViewerMode Mode { get; private set; }
        public LiveModel Live { get { return live; } }

        // Les lignes reçues de Python qu'on n'a pas su lire (comptées et affichées, sans rien planter).
        public int RejectedLines { get; private set; }
        public string LastLineError { get; private set; }

        public bool IsLiveConnected
        {
            get { return connection != null && connection.IsConnected; }
        }

        // L'état de la liaison, pour le panneau de gauche.
        public string ConnectionText
        {
            get
            {
                if (connection == null)
                {
                    return "";
                }
                if (connection.IsConnected)
                {
                    return "Connecté à Python";
                }
                return "Python ne répond pas (127.0.0.1:" + port + "), nouvel essai toutes les secondes.";
            }
        }

        // Crée le visualiseur au lancement du Play, s'il n'y en a pas déjà un.
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
            if (FindFirstObjectByType<CircuitViewer>() == null)
            {
                new GameObject("CircuitViewer").AddComponent<CircuitViewer>();
            }
        }

        public static string DefaultFolder()
        {
            return Path.GetFullPath(Path.Combine(Application.dataPath, "..", "circuits"));
        }

        void Start()
        {
            Refresh();
            if (files.Count > 0) Select(0);
        }

        void Update()
        {
            Tick(Time.deltaTime);
        }

        // Ce qui se passe à chaque image (public pour que les tests puissent la jouer sans attendre Unity).
        public void Tick(float deltaTime)
        {
            RunPendingAction();
            if (Mode == ViewerMode.Live)
            {
                TickLive(deltaTime);
            }
            else if (Screen.width != lastScreenWidth && Current != null)
            {
                // La liste occupe une largeur fixe en pixels : on recadre si la fenêtre change.
                lastScreenWidth = Screen.width;
                FitCamera(Current);
            }
        }

        void RunPendingAction()
        {
            Action action = pendingAction;
            pendingAction = null;
            if (action != null) action();
        }

        // Relit la liste des fichiers du dossier.
        public void Refresh()
        {
            files.Clear();
            string path = string.IsNullOrEmpty(folder) ? DefaultFolder() : folder;
            if (!Directory.Exists(path))
            {
                ErrorMessage = "dossier introuvable : " + path;
                return;
            }
            files.AddRange(Directory.GetFiles(path, "*.json"));
            files.Sort(StringComparer.Ordinal);
            ErrorMessage = files.Count == 0 ? "aucun fichier .json dans " + path : null;
        }

        // Charge et dessine le fichier numéro « index » de la liste. Un fichier invalide ne
        // plante rien : le message d'erreur est gardé pour être affiché.
        public void Select(int index)
        {
            if (index < 0 || index >= files.Count) return;
            selected = index;
            ClearDrawing();
            try
            {
                Current = CircuitLoader.Load(files[index]);
                ErrorMessage = null;
                drawn = CircuitDrawer.Draw(Current);
                FitCamera(Current);
            }
            catch (CircuitFormatException exception)
            {
                Current = null;
                ErrorMessage = exception.Message;
            }
        }

        void ClearDrawing()
        {
            if (drawn == null) return;
            if (Application.isPlaying) Destroy(drawn);
            else DestroyImmediate(drawn);
            drawn = null;
        }

        void OnDestroy()
        {
            StopConnection();
            ClearDrawing();
        }

        // Cadre la caméra sur un circuit (la partie à droite de la liste). Sans circuit ou sans caméra : rien.
        void FitCamera(CircuitFile target)
        {
            Camera camera = Camera.main;
            if (camera == null || target == null) return;
            // La caméra ne dessine que la partie à droite de la liste.
            float fraction = Mathf.Clamp01(PanelWidth / Mathf.Max(Screen.width, 1));
            camera.rect = new Rect(fraction, 0f, 1f - fraction, 1f);
            Vector2 center;
            float size;
            CircuitGeometry.FitCamera(CircuitGeometry.Bounds(target, Margin), camera.aspect, out center, out size);
            camera.orthographic = true;
            camera.orthographicSize = size;
            camera.transform.position = new Vector3(center.x, center.y, camera.transform.position.z);
        }

        // --- Le mode « En direct » ----------------------------------------------------------

        // Se connecte à Python et montre le direct. Sans effet si on y est déjà.
        public void EnterLiveMode()
        {
            if (Mode == ViewerMode.Live) return;
            var newConnection = new LiveConnection(port);
            ClearDrawing();
            Mode = ViewerMode.Live;
            drawnVersion = -1;
            fitted = null;
            lineConnection = 0;
            connection = newConnection;
            connection.Start();
        }

        // Coupe la liaison et revient aux fichiers du dossier. Sans effet si on y est déjà.
        public void EnterFilesMode()
        {
            if (Mode == ViewerMode.Files) return;
            StopConnection();
            Mode = ViewerMode.Files;
            ClearDrawing();
            if (selected >= 0) Select(selected);
        }

        void StopConnection()
        {
            if (connection == null) return;
            connection.Dispose();
            connection = null;
        }

        void TickLive(float deltaTime)
        {
            if (Screen.width != lastScreenWidth)
            {
                lastScreenWidth = Screen.width;
                fitted = null;
            }
            live.Advance(Mathf.Min(deltaTime, MaxFrameSeconds));
            ProcessIncoming();
        }

        // Lit les lignes reçues de Python, les passe au modèle, puis redessine si le dessin a changé.
        // Une ligne illisible est comptée (RejectedLines) et ne plante rien.
        public void ProcessIncoming()
        {
            if (Mode != ViewerMode.Live || connection == null) return;
            string line;
            int number;
            int processed = 0;
            while (processed < MaxLinesPerFrame && connection.TryDequeue(out line, out number))
            {
                processed++;
                if (number != lineConnection)
                {
                    // Une nouvelle session de Python : l'ancienne bibliothèque n'a plus de sens (Python
                    // renvoie tout son historique à chaque connexion).
                    live.Reset();
                    lineConnection = number;
                }
                try
                {
                    live.Apply(LiveMessageParser.Parse(line));
                }
                catch (LiveMessageException exception)
                {
                    RejectedLines++;
                    LastLineError = exception.Message;
                }
            }
            RedrawLive();
        }

        // Redessine seulement si le modèle a changé le circuit montré, et recadre si la cible a changé.
        void RedrawLive()
        {
            if (live.Version != drawnVersion)
            {
                drawnVersion = live.Version;
                ClearDrawing();
                if (live.Shown != null) drawn = CircuitDrawer.Draw(live.Shown);
            }
            if (!ReferenceEquals(fitted, live.FitTarget))
            {
                fitted = live.FitTarget;
                FitCamera(fitted);
            }
        }

        // --- Interface minimale (IMGUI : fonctionne avec le nouveau système d'entrée) ----

        void OnGUI()
        {
            GUILayout.BeginArea(new Rect(0f, 0f, PanelWidth, Screen.height), GUI.skin.box);
            DrawModeButtons();
            if (Mode == ViewerMode.Live) DrawLivePanel();
            else DrawFilesPanel();
            GUILayout.EndArea();

            string status = StatusLine();
            if (status != null)
            {
                GUI.Label(new Rect(PanelWidth + 10f, 8f, Screen.width - PanelWidth - 20f, 24f), status);
            }
        }

        void DrawModeButtons()
        {
            GUILayout.BeginHorizontal();
            if (GUILayout.Toggle(Mode == ViewerMode.Files, "Fichiers", GUI.skin.button) && Mode != ViewerMode.Files)
            {
                pendingAction = EnterFilesMode;
            }
            if (GUILayout.Toggle(Mode == ViewerMode.Live, "En direct", GUI.skin.button) && Mode != ViewerMode.Live)
            {
                pendingAction = EnterLiveMode;
            }
            GUILayout.EndHorizontal();
        }

        void DrawFilesPanel()
        {
            GUILayout.Label("Circuits (" + files.Count + ")");
            scroll = GUILayout.BeginScrollView(scroll);
            for (int i = 0; i < files.Count; i++)
            {
                string name = Path.GetFileNameWithoutExtension(files[i]);
                bool isCurrent = i == selected;
                if (GUILayout.Toggle(isCurrent, name, GUI.skin.button) && !isCurrent)
                {
                    Select(i);
                }
            }
            GUILayout.EndScrollView();
        }

        // L'état de la liaison, les statistiques, la bibliothèque des découvertes (un clic la rediffuse)
        // et, pendant une rediffusion, ses commandes.
        void DrawLivePanel()
        {
            GUILayout.Label(ConnectionText);
            GUILayout.Label(live.StatsText);
            GUILayout.Label("Bibliothèque (" + live.Discoveries.Count + ")");
            scroll = GUILayout.BeginScrollView(scroll);
            for (int i = 0; i < live.Discoveries.Count; i++)
            {
                DiscoveryData discovery = live.Discoveries[i];
                bool isReplayed = ReferenceEquals(discovery, live.Replayed);
                if (GUILayout.Toggle(isReplayed, LiveModel.DiscoveryLabel(discovery), GUI.skin.button) && !isReplayed)
                {
                    int index = i;
                    pendingAction = () => live.StartReplay(index);
                }
            }
            GUILayout.EndScrollView();
            if (live.View == LiveView.Replay) DrawReplayControls();
        }

        void DrawReplayControls()
        {
            GUILayout.Label("Rediffusion : étape " + live.ReplayStep + "/" + live.ReplayStepCount);
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("<")) pendingAction = live.StepBack;
            if (GUILayout.Button(live.IsPlaying ? "Pause" : "Lecture")) pendingAction = live.TogglePause;
            if (GUILayout.Button(">")) pendingAction = live.StepForward;
            GUILayout.EndHorizontal();
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("Début")) pendingAction = live.Restart;
            if (GUILayout.Button("Direct")) pendingAction = live.ReturnToDirect;
            GUILayout.EndHorizontal();
        }

        // Le résumé affiché en haut : nom, top, stabilité ; ou le message d'erreur.
        string StatusLine()
        {
            if (Mode == ViewerMode.Live) return LiveStatusLine();
            if (!string.IsNullOrEmpty(ErrorMessage)) return "ERREUR : " + ErrorMessage;
            if (Current == null) return null;
            if (!CircuitLoader.HasState(Current)) return Current.nom + " (sans valeurs)";
            string stability = Current.etat.stable ? "stable" : "INSTABLE";
            return Current.nom + " - top " + Current.etat.top + " - " + stability;
        }

        string LiveStatusLine()
        {
            if (RejectedLines == 0) return live.Caption;
            return live.Caption + " - " + RejectedLines + " ligne(s) illisible(s) (" + LastLineError + ")";
        }
    }
}
