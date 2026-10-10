using NUnit.Framework;

namespace LogicAI.Tests
{
    // Tests de la logique de l'affichage en direct : quoi dessiner, la bibliothèque, la rediffusion.
    // Aucune horloge : le temps est passé à Advance, donc les tests sont déterministes.
    public class LiveModelTests
    {
        LiveModel model;

        [SetUp]
        public void SetUp()
        {
            model = new LiveModel();
        }

        static LiveMessage Message(string sample)
        {
            return LiveMessageParser.Parse(LiveSamples.Json(sample));
        }

        static int PieceCount(CircuitFile file)
        {
            return file.noeuds.Length + file.cables.Length;
        }

        // Fait avancer la rediffusion d'exactement « count » pièces.
        void AdvanceSteps(int count)
        {
            for (int i = 0; i < count; i++)
            {
                model.Advance(LiveModel.ReplayStepSeconds);
            }
        }

        // Une bibliothèque avec le NOT (6 étapes) puis le XOR (16 étapes), la rediffusion du NOT lancée.
        void ReplayingNot()
        {
            model.Apply(Message(LiveSamples.NotDiscoveryLine));
            model.Apply(Message(LiveSamples.XorDiscoveryLine));
            Assert.IsTrue(model.StartReplay(0));
        }

        // --- État initial ----------------------------------------------------------------

        [Test]
        public void NewModel_ShowsNothing_AndWaits()
        {
            Assert.IsNull(model.Shown);
            Assert.AreEqual(0, model.Version);
            Assert.AreEqual(LiveView.Direct, model.View);
            Assert.AreEqual(0, model.Discoveries.Count);
            Assert.IsNull(model.Stats);
            Assert.AreEqual(0, model.IgnoredFrames);
            Assert.AreEqual("en attente d'un essai...", model.Caption);
            Assert.AreEqual("en attente de statistiques", model.StatsText);
        }

        [Test]
        public void Apply_Null_IsRefused()
        {
            Assert.Throws<System.ArgumentNullException>(() => model.Apply(null));
        }

        // --- Le direct -------------------------------------------------------------------

        [Test]
        public void Circuit_BecomesTheShownCircuit_WithoutValues()
        {
            // Règle vérifiée : plan de la phase 5 (étape 9) : un message « circuit » est dessiné tel quel.
            model.Apply(Message(LiveSamples.CircuitLine));

            Assert.IsNotNull(model.Shown);
            Assert.AreEqual("essai", model.Shown.nom);
            Assert.IsFalse(CircuitLoader.HasState(model.Shown));
            Assert.AreEqual(1, model.Version);
            Assert.AreSame(model.Shown, model.FitTarget);
            Assert.AreEqual("essai en direct (en attente des valeurs)", model.Caption);
        }

        [Test]
        public void State_AfterTheCircuit_ColorsIt()
        {
            // Règle vérifiée : un message « etat » donne les valeurs 0/1 du circuit courant.
            model.Apply(Message(LiveSamples.CircuitLine));
            model.Apply(Message(LiveSamples.StateLine));

            Assert.IsTrue(CircuitLoader.HasState(model.Shown));
            Assert.AreEqual(1, model.Shown.etat.top);
            Assert.AreEqual(2, model.Version);
            Assert.AreEqual("essai en direct - top 1 - stable", model.Caption);
        }

        [Test]
        public void UnstableState_IsAnnounced()
        {
            model.Apply(Message(LiveSamples.CircuitLine));
            model.Apply(Message(LiveSamples.StateLine.Replace("'stable':true", "'stable':false")));

            Assert.AreEqual("essai en direct - top 1 - INSTABLE", model.Caption);
        }

        [Test]
        public void State_BeforeAnyCircuit_IsIgnored()
        {
            // Règle vérifiée : un Unity qui se connecte en pleine animation reçoit des « etat » sans
            // le « circuit » parti avant lui (journal de la phase 5, étape 5).
            model.Apply(Message(LiveSamples.StateLine));

            Assert.IsNull(model.Shown);
            Assert.AreEqual(0, model.Version);
            Assert.AreEqual(1, model.IgnoredFrames);
        }

        [Test]
        public void State_OfAnotherSize_IsIgnored_AndKeepsThePreviousValues()
        {
            // Règle vérifiée : le serveur peut jeter un « circuit » en gardant ses « etat » : une image
            // qui ne correspond pas au circuit courant n'est pas montrée.
            model.Apply(Message(LiveSamples.CircuitLine));
            model.Apply(Message(LiveSamples.StateLine));
            CircuitFile before = model.Shown;
            int version = model.Version;
            var wrong = new LiveMessage
            {
                Kind = LiveMessageKind.State,
                State = new StateData { top = 9, stable = true, noeuds = new[] { 0, 1 }, cables = new[] { 0, 0, 1 } },
            };

            model.Apply(wrong);

            Assert.AreEqual(1, model.IgnoredFrames);
            Assert.AreEqual(version, model.Version);
            Assert.AreSame(before, model.Shown);
            Assert.AreEqual(1, model.Shown.etat.top);
        }

        [Test]
        public void State_WithMissingArrays_IsIgnored()
        {
            model.Apply(Message(LiveSamples.CircuitLine));
            var noNodes = new LiveMessage { Kind = LiveMessageKind.State, State = new StateData { top = 1, stable = true, cables = new[] { 0, 0, 1 } } };
            var noWires = new LiveMessage { Kind = LiveMessageKind.State, State = new StateData { top = 1, stable = true, noeuds = new[] { 0, 1, 1 } } };

            model.Apply(noNodes);
            model.Apply(noWires);

            Assert.AreEqual(2, model.IgnoredFrames);
            Assert.AreEqual(1, model.Version);
            Assert.IsFalse(CircuitLoader.HasState(model.Shown));
        }

        [Test]
        public void NewCircuit_ForgetsThePreviousValues()
        {
            // Règle vérifiée : les valeurs de l'ancien essai ne colorent pas le nouveau circuit.
            model.Apply(Message(LiveSamples.CircuitLine));
            model.Apply(Message(LiveSamples.StateLine));

            model.Apply(Message(LiveSamples.CircuitLine));

            Assert.IsFalse(CircuitLoader.HasState(model.Shown));
            Assert.AreEqual(3, model.Version);
        }

        // --- Statistiques ----------------------------------------------------------------

        [Test]
        public void Stats_AreKept_AndWrittenInFrench()
        {
            model.Apply(Message(LiveSamples.StatsLine));

            Assert.AreEqual(2, model.Stats.palier);
            Assert.AreEqual("Palier 2 - génération 40 - 5 découvertes - récompense moyenne 1.98", model.StatsText);
            Assert.AreEqual(0, model.Version, "les statistiques ne changent pas le dessin");
        }

        [Test]
        public void Stats_WithASingleDiscovery_UseTheSingular()
        {
            model.Apply(Message(LiveSamples.StatsLine.Replace("'decouvertes':5", "'decouvertes':1")));

            Assert.AreEqual("Palier 2 - génération 40 - 1 découverte - récompense moyenne 1.98", model.StatsText);
        }

        [Test]
        public void NewerStats_ReplaceTheOlderOnes()
        {
            model.Apply(Message(LiveSamples.StatsLine));
            model.Apply(Message(LiveSamples.StatsLine.Replace("'generation':40", "'generation':41")));

            Assert.AreEqual(41, model.Stats.generation);
        }

        // --- La bibliothèque -------------------------------------------------------------

        [Test]
        public void Discoveries_AreKeptInOrderOfArrival_WithoutChangingTheDrawing()
        {
            model.Apply(Message(LiveSamples.NotDiscoveryLine));
            model.Apply(Message(LiveSamples.XorDiscoveryLine));

            Assert.AreEqual(2, model.Discoveries.Count);
            Assert.AreEqual("NOT", model.Discoveries[0].nom);
            Assert.AreEqual("XOR", model.Discoveries[1].nom);
            Assert.AreEqual(0, model.Version);
            Assert.IsNull(model.Shown);
        }

        [Test]
        public void SameDiscoveryReceivedAgain_ReplacesTheEntry_WithoutDuplicate()
        {
            // Règle vérifiée : à chaque connexion Python renvoie tout l'historique des découvertes
            // (journal de la phase 5, étape 3) : la bibliothèque n'a pas de doublons.
            model.Apply(Message(LiveSamples.NotDiscoveryLine));
            DiscoveryData first = model.Discoveries[0];
            DiscoveryData again = Message(LiveSamples.NotDiscoveryLine).Discovery;

            model.Apply(new LiveMessage { Kind = LiveMessageKind.Discovery, Discovery = again });

            Assert.AreEqual(1, model.Discoveries.Count);
            Assert.AreNotSame(first, model.Discoveries[0]);
            Assert.AreSame(again, model.Discoveries[0]);
        }

        [Test]
        public void SameNameWithAnotherGenreOrCost_IsAnotherEntry()
        {
            // Un record est une version plus petite d'un composant connu : il s'ajoute à la nouveauté.
            model.Apply(Message(LiveSamples.NotDiscoveryLine));
            model.Apply(Message(LiveSamples.NotDiscoveryLine.Replace("'nouveaute'", "'record'").Replace("'cout':1", "'cout':0")));
            model.Apply(Message(LiveSamples.NotDiscoveryLine.Replace("'nouveaute'", "'record'").Replace("'cout':1", "'cout':2")));

            Assert.AreEqual(3, model.Discoveries.Count);
        }

        [Test]
        public void DiscoveryLabel_NamesTheGenreAndTheCost()
        {
            Assert.AreEqual("NOT - nouveauté - 1 NAND", LiveModel.DiscoveryLabel(Message(LiveSamples.NotDiscoveryLine).Discovery));
            Assert.AreEqual("XOR - record - 4 NAND", LiveModel.DiscoveryLabel(Message(LiveSamples.XorDiscoveryLine).Discovery));
        }

        [Test]
        public void Reset_ForgetsEverything()
        {
            // Règle vérifiée : à une nouvelle connexion, on repart de zéro (Python renvoie l'historique).
            model.Apply(Message(LiveSamples.CircuitLine));
            model.Apply(Message(LiveSamples.StateLine));
            model.Apply(Message(LiveSamples.NotDiscoveryLine));
            model.Apply(Message(LiveSamples.StatsLine));
            model.Apply(Message(LiveSamples.StateLine.Replace("'noeuds':[0,1,1]", "'noeuds':[0]")));
            int version = model.Version;

            model.Reset();

            Assert.AreEqual(0, model.Discoveries.Count);
            Assert.IsNull(model.Shown);
            Assert.IsNull(model.Stats);
            Assert.AreEqual(0, model.IgnoredFrames);
            Assert.AreEqual(LiveView.Direct, model.View);
            Assert.AreEqual(version + 1, model.Version, "le dessin a été effacé : le viewer doit le savoir");
            Assert.AreEqual("en attente d'un essai...", model.Caption);
        }

        [Test]
        public void Reset_OnAnEmptyModel_ChangesNothing()
        {
            model.Reset();

            Assert.AreEqual(0, model.Version);
        }

        // --- La rediffusion --------------------------------------------------------------

        [Test]
        public void StartReplay_WithAnInvalidIndex_IsRefused()
        {
            Assert.IsFalse(model.StartReplay(0), "bibliothèque vide");
            model.Apply(Message(LiveSamples.NotDiscoveryLine));

            Assert.IsFalse(model.StartReplay(-1));
            Assert.IsFalse(model.StartReplay(1));
            Assert.AreEqual(LiveView.Direct, model.View);
        }

        [Test]
        public void StartReplay_BeginsWithNothingPlaced_AndPlays()
        {
            ReplayingNot();

            Assert.AreEqual(LiveView.Replay, model.View);
            Assert.AreEqual("NOT", model.Replayed.nom);
            Assert.AreEqual(0, model.ReplayStep);
            Assert.AreEqual(6, model.ReplayStepCount);
            Assert.IsTrue(model.IsPlaying);
            Assert.IsNull(model.Shown, "rien n'est encore posé");
        }

        [Test]
        public void StartReplay_ChoosesTheRequestedDiscovery()
        {
            ReplayingNot();

            Assert.IsTrue(model.StartReplay(1));

            Assert.AreEqual("XOR", model.Replayed.nom);
            Assert.AreEqual(16, model.ReplayStepCount);
            Assert.AreEqual(0, model.ReplayStep);
        }

        [Test]
        public void Advance_PlacesOneNodeThenOneWireAtATime()
        {
            // Règle vérifiée : cahier, « les nœuds dans l'ordre des signaux, puis les câbles ».
            ReplayingNot();

            for (int step = 1; step <= 6; step++)
            {
                AdvanceSteps(1);
                Assert.AreEqual(step, model.ReplayStep);
                Assert.AreEqual(step, PieceCount(model.Shown), "après " + step + " étapes");
                Assert.AreEqual(step <= 3 ? step : 3, model.Shown.noeuds.Length);
                Assert.AreEqual(step <= 3 ? 0 : step - 3, model.Shown.cables.Length);
            }
        }

        [Test]
        public void Advance_ToTheEnd_ShowsTheWholeCircuit_AndStopsPlaying()
        {
            ReplayingNot();

            AdvanceSteps(6);

            Assert.IsFalse(model.IsPlaying);
            Assert.AreEqual(3, model.Shown.noeuds.Length);
            Assert.AreEqual(3, model.Shown.cables.Length);
            Assert.AreEqual("NOT", model.Shown.nom);
        }

        [Test]
        public void Advance_AfterTheEnd_ChangesNothing()
        {
            ReplayingNot();
            AdvanceSteps(6);
            int version = model.Version;

            model.Advance(100f);

            Assert.AreEqual(6, model.ReplayStep);
            Assert.AreEqual(version, model.Version);
        }

        [Test]
        public void Advance_LessThanOneStep_ChangesNothing_ButTimeAccumulates()
        {
            ReplayingNot();
            int version = model.Version;

            model.Advance(LiveModel.ReplayStepSeconds / 2f);

            Assert.AreEqual(0, model.ReplayStep);
            Assert.AreEqual(version, model.Version);

            model.Advance(LiveModel.ReplayStepSeconds / 2f);

            Assert.AreEqual(1, model.ReplayStep);
        }

        [Test]
        public void Advance_ALongFrame_PlacesSeveralPieces()
        {
            ReplayingNot();

            model.Advance(LiveModel.ReplayStepSeconds * 3.25f);

            Assert.AreEqual(3, model.ReplayStep);
            Assert.AreEqual(3, PieceCount(model.Shown));
        }

        [Test]
        public void Advance_ZeroOrNegativeTime_ChangesNothing()
        {
            ReplayingNot();

            model.Advance(0f);
            model.Advance(-5f);

            Assert.AreEqual(0, model.ReplayStep);
        }

        [Test]
        public void Advance_VeryLongTime_StopsAtTheEnd()
        {
            ReplayingNot();

            model.Advance(1000f);

            Assert.AreEqual(6, model.ReplayStep);
            Assert.IsFalse(model.IsPlaying);
        }

        [Test]
        public void EachPlacedPiece_RaisesTheVersionByOne()
        {
            // Règle vérifiée : le viewer redessine exactement quand le dessin change.
            ReplayingNot();
            AdvanceSteps(1);
            int version = model.Version;

            AdvanceSteps(1);

            Assert.AreEqual(version + 1, model.Version);
        }

        [Test]
        public void TheLastStepOfTheXor_GivesTheWholeCircuitOfTheMessage()
        {
            model.Apply(Message(LiveSamples.XorDiscoveryLine));
            model.StartReplay(0);

            AdvanceSteps(7);
            Assert.AreEqual(7, model.Shown.noeuds.Length);
            Assert.AreEqual(0, model.Shown.cables.Length, "les 7 nœuds sont posés avant le 1er câble");
            AdvanceSteps(1);
            Assert.AreEqual(1, model.Shown.cables.Length);
            AdvanceSteps(8);

            Assert.AreEqual(7, model.Shown.noeuds.Length);
            Assert.AreEqual(9, model.Shown.cables.Length);
            Assert.IsFalse(model.IsPlaying);
        }

        [Test]
        public void TheCameraStaysOnTheWholeCircuit_DuringTheReplay()
        {
            // Règle vérifiée : décision du plan : la caméra reste cadrée sur le circuit complet.
            ReplayingNot();

            Assert.AreSame(model.Replayed.circuit, model.FitTarget);
            AdvanceSteps(2);
            Assert.AreSame(model.Replayed.circuit, model.FitTarget);
        }

        [Test]
        public void Caption_DuringTheReplay_NamesTheDiscoveryAndTheStep()
        {
            ReplayingNot();
            Assert.AreEqual("NOT - nouveauté - 1 NAND - étape 0/6", model.Caption);

            AdvanceSteps(1);

            Assert.AreEqual("NOT - nouveauté - 1 NAND - étape 1/6", model.Caption);
        }

        // --- Pas à pas, pause, recommencer -----------------------------------------------

        [Test]
        public void StepForward_Pauses_AndPlacesOnePiece()
        {
            ReplayingNot();

            model.StepForward();

            Assert.IsFalse(model.IsPlaying);
            Assert.AreEqual(1, model.ReplayStep);
            Assert.AreEqual(1, PieceCount(model.Shown));
        }

        [Test]
        public void StepForward_AtTheEnd_StaysThere()
        {
            ReplayingNot();
            AdvanceSteps(6);
            int version = model.Version;

            model.StepForward();

            Assert.AreEqual(6, model.ReplayStep);
            Assert.AreEqual(version, model.Version);
        }

        [Test]
        public void StepBack_RemovesOnePiece_AndStopsAtZero()
        {
            ReplayingNot();
            AdvanceSteps(2);

            model.StepBack();

            Assert.IsFalse(model.IsPlaying);
            Assert.AreEqual(1, model.ReplayStep);
            Assert.AreEqual(1, PieceCount(model.Shown));

            model.StepBack();
            Assert.AreEqual(0, model.ReplayStep);
            Assert.IsNull(model.Shown);

            int version = model.Version;
            model.StepBack();
            Assert.AreEqual(0, model.ReplayStep);
            Assert.AreEqual(version, model.Version);
        }

        [Test]
        public void TogglePause_StopsAndResumesThePlayback()
        {
            ReplayingNot();
            AdvanceSteps(1);

            model.TogglePause();
            model.Advance(100f);

            Assert.IsFalse(model.IsPlaying);
            Assert.AreEqual(1, model.ReplayStep, "en pause, le temps n'avance pas la lecture");

            model.TogglePause();
            Assert.IsTrue(model.IsPlaying);
            AdvanceSteps(1);

            Assert.AreEqual(2, model.ReplayStep);
        }

        [Test]
        public void TogglePause_AtTheEnd_RestartsFromTheBeginning()
        {
            ReplayingNot();
            AdvanceSteps(6);
            Assert.IsFalse(model.IsPlaying);

            model.TogglePause();

            Assert.IsTrue(model.IsPlaying);
            Assert.AreEqual(0, model.ReplayStep);
            Assert.IsNull(model.Shown);
        }

        [Test]
        public void Restart_GoesBackToZero_AndPlays()
        {
            ReplayingNot();
            AdvanceSteps(4);

            model.Restart();

            Assert.AreEqual(0, model.ReplayStep);
            Assert.IsTrue(model.IsPlaying);
            Assert.IsNull(model.Shown);
        }

        [Test]
        public void Replay_OfADiscoveryWithoutSteps_DoesNothingAndDoesNotThrow()
        {
            var empty = new DiscoveryData
            {
                nom = "VIDE",
                genre = LiveMessageParser.NewGenre,
                cout = 0,
                circuit = new CircuitFile { nom = "VIDE", noeuds = new NodeData[0], cables = new WireData[0] },
                ordre_de_pose = new PlacementStep[0],
            };
            model.Apply(new LiveMessage { Kind = LiveMessageKind.Discovery, Discovery = empty });

            Assert.IsTrue(model.StartReplay(0));
            model.Advance(10f);
            model.TogglePause();

            Assert.IsFalse(model.IsPlaying);
            Assert.AreEqual(0, model.ReplayStep);
            Assert.IsNull(model.Shown);
        }

        // --- Retour au direct, et le direct qui continue pendant une rediffusion ---------

        [Test]
        public void ReturnToDirect_ShowsTheLatestLiveCircuitAgain()
        {
            model.Apply(Message(LiveSamples.CircuitLine));
            model.Apply(Message(LiveSamples.StateLine));
            model.Apply(Message(LiveSamples.NotDiscoveryLine));
            model.StartReplay(0);
            AdvanceSteps(2);

            model.ReturnToDirect();

            Assert.AreEqual(LiveView.Direct, model.View);
            Assert.IsNull(model.Replayed);
            Assert.IsFalse(model.IsPlaying);
            Assert.AreEqual("essai", model.Shown.nom);
            Assert.IsTrue(CircuitLoader.HasState(model.Shown));
            Assert.AreEqual("essai en direct - top 1 - stable", model.Caption);
        }

        [Test]
        public void ReturnToDirect_WithoutAnyLiveCircuit_ShowsNothing()
        {
            ReplayingNot();
            AdvanceSteps(2);

            model.ReturnToDirect();

            Assert.IsNull(model.Shown);
            Assert.AreEqual("en attente d'un essai...", model.Caption);
        }

        [Test]
        public void LiveMessages_DuringAReplay_DoNotDisturbIt_ButAreKept()
        {
            // Règle vérifiée : cahier, « l'entraînement continue à pleine vitesse » : pendant qu'on
            // regarde une rediffusion, le direct continue d'arriver et d'être gardé.
            ReplayingNot();
            AdvanceSteps(2);
            int version = model.Version;
            int step = model.ReplayStep;

            model.Apply(Message(LiveSamples.CircuitLine));
            model.Apply(Message(LiveSamples.StateLine));
            model.Apply(Message(LiveSamples.StatsLine));

            Assert.AreEqual(version, model.Version);
            Assert.AreEqual(step, model.ReplayStep);
            Assert.AreEqual(LiveView.Replay, model.View);

            model.ReturnToDirect();

            Assert.AreEqual("essai", model.Shown.nom);
            Assert.IsTrue(CircuitLoader.HasState(model.Shown));
        }

        [Test]
        public void NewDiscovery_DuringAReplay_JoinsTheLibrary_WithoutDisturbingIt()
        {
            ReplayingNot();
            AdvanceSteps(2);
            int version = model.Version;

            model.Apply(Message(LiveSamples.XorDiscoveryLine.Replace("'nom':'XOR','genre'", "'nom':'XOR2','genre'")));

            Assert.AreEqual(3, model.Discoveries.Count);
            Assert.AreEqual(version, model.Version);
            Assert.AreEqual(2, model.ReplayStep);
        }

        [Test]
        public void ReplacingTheReplayedEntry_DoesNotDisturbTheReplay()
        {
            // Règle vérifiée : après une reconnexion Python renvoie l'historique ; la rediffusion en
            // cours (mémorisée) continue sans saut.
            ReplayingNot();
            AdvanceSteps(1);
            DiscoveryData replayed = model.Replayed;

            model.Apply(Message(LiveSamples.NotDiscoveryLine));

            Assert.AreNotSame(replayed, model.Discoveries[0]);
            Assert.AreSame(replayed, model.Replayed);
            AdvanceSteps(1);
            Assert.AreEqual(2, PieceCount(model.Shown));
        }

        [Test]
        public void Reset_DuringAReplay_ReturnsToDirectAndClearsIt()
        {
            ReplayingNot();
            AdvanceSteps(2);

            model.Reset();

            Assert.AreEqual(LiveView.Direct, model.View);
            Assert.IsNull(model.Replayed);
            Assert.IsFalse(model.IsPlaying);
            Assert.IsNull(model.Shown);
            Assert.AreEqual(0, model.Discoveries.Count);
        }

        [Test]
        public void ReplayControls_InTheDirectView_DoNothing()
        {
            model.Apply(Message(LiveSamples.CircuitLine));
            int version = model.Version;

            model.Advance(10f);
            model.StepForward();
            model.StepBack();
            model.TogglePause();
            model.Restart();
            model.ReturnToDirect();

            Assert.AreEqual(LiveView.Direct, model.View);
            Assert.AreEqual(version, model.Version);
            Assert.IsFalse(model.IsPlaying);
            Assert.AreEqual(0, model.ReplayStep);
        }
    }
}
