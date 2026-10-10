using System.Collections.Generic;
using NUnit.Framework;

namespace LogicAI.Tests
{
    // Tests du rejeu d'un ordre de pose : les premières étapes donnent un circuit partiel.
    public class LivePlacementTests
    {
        // Les 16 étapes de pose du XOR, écrites par Python (7 nœuds puis 9 câbles).
        static PlacementStep[] XorSteps()
        {
            return LiveMessageParser.Parse(LiveSamples.Json(LiveSamples.XorDiscoveryLine)).Discovery.ordre_de_pose;
        }

        static CircuitFile XorCircuit()
        {
            return LiveMessageParser.Parse(LiveSamples.Json(LiveSamples.XorDiscoveryLine)).Discovery.circuit;
        }

        static PlacementStep Pose(int id, string type)
        {
            return new PlacementStep { action = LivePlacement.PoseAction, noeud = new NodeData { id = id, type = type } };
        }

        static PlacementStep Wire(int fromNode, int fromPin, int toNode, int toPin)
        {
            return new PlacementStep
            {
                action = LivePlacement.WireAction,
                de = new[] { fromNode, fromPin },
                vers = new[] { toNode, toPin },
            };
        }

        static void AssertRefused(PlacementStep[] steps, int count, string expectedPart)
        {
            var exception = Assert.Throws<CircuitFormatException>(() => LivePlacement.BuildCircuit("TEST", steps, count));
            StringAssert.Contains(expectedPart, exception.Message);
        }

        // Les câbles d'un circuit sous forme de textes comparables, quel que soit leur ordre.
        static List<string> WireTexts(CircuitFile file)
        {
            var texts = new List<string>();
            foreach (WireData wire in file.cables)
            {
                texts.Add(wire.de[0] + "," + wire.de[1] + ">" + wire.vers[0] + "," + wire.vers[1]);
            }
            return texts;
        }

        // --- Rejeu ---------------------------------------------------------------

        [Test]
        public void BuildCircuit_WithZeroSteps_IsAnEmptyCircuitWithItsName()
        {
            // Règle vérifiée : avant la 1re étape, la rediffusion ne montre encore rien.
            CircuitFile file = LivePlacement.BuildCircuit("XOR", XorSteps(), 0);

            Assert.AreEqual("XOR", file.nom);
            Assert.AreEqual(0, file.noeuds.Length);
            Assert.AreEqual(0, file.cables.Length);
        }

        [Test]
        public void BuildCircuit_EveryPrefixGrowsByOnePiece()
        {
            // Règle vérifiée : après k étapes, le circuit a k pièces (nœuds et câbles) ; chaque
            // circuit partiel est cohérent (BuildCircuit le vérifie), donc dessinable.
            PlacementStep[] steps = XorSteps();

            for (int count = 0; count <= steps.Length; count++)
            {
                CircuitFile file = LivePlacement.BuildCircuit("XOR", steps, count);
                Assert.AreEqual(count, file.noeuds.Length + file.cables.Length, "après " + count + " étapes");
            }
        }

        [Test]
        public void BuildCircuit_AllSteps_GivesTheCircuitOfTheMessage()
        {
            // Règle vérifiée : rejouer tout l'ordre de pose redonne le circuit de la découverte.
            CircuitFile rebuilt = LivePlacement.BuildCircuit("XOR", XorSteps(), XorSteps().Length);
            CircuitFile original = XorCircuit();

            Assert.AreEqual(original.noeuds.Length, rebuilt.noeuds.Length);
            CollectionAssert.AreEquivalent(WireTexts(original), WireTexts(rebuilt));
            foreach (NodeData node in rebuilt.noeuds)
            {
                NodeData same = System.Array.Find(original.noeuds, candidate => candidate.id == node.id);
                Assert.IsNotNull(same, "nœud " + node.id);
                Assert.AreEqual(same.type, node.type);
                Assert.AreEqual(same.x, node.x);
                Assert.AreEqual(same.y, node.y);
            }
        }

        [Test]
        public void BuildCircuit_CountLargerThanTheOrder_MeansEverything()
        {
            CircuitFile file = LivePlacement.BuildCircuit("XOR", XorSteps(), 999);

            Assert.AreEqual(7, file.noeuds.Length);
            Assert.AreEqual(9, file.cables.Length);
        }

        // --- Ordres incohérents refusés ---------------------------------------------

        [Test]
        public void BuildCircuit_MissingSteps_IsRefused()
        {
            AssertRefused(null, 1, "manque");
        }

        [Test]
        public void BuildCircuit_NegativeCount_IsRefused()
        {
            AssertRefused(XorSteps(), -1, "négatif");
        }

        [Test]
        public void BuildCircuit_WireBeforeItsNode_IsRefused()
        {
            // Règle vérifiée : « les nœuds, puis les câbles » : un câble ne vient qu'après la pose
            // de ses deux nœuds.
            var steps = new[] { Pose(0, "ENTREE"), Wire(0, 0, 1, 0), Pose(1, "NAND") };

            AssertRefused(steps, 3, "pas encore posé");
        }

        [Test]
        public void BuildCircuit_UnknownAction_IsRefused()
        {
            var steps = new[] { new PlacementStep { action = "jeter" } };

            AssertRefused(steps, 1, "action inconnue");
        }

        [Test]
        public void BuildCircuit_PoseWithoutANode_IsRefused()
        {
            var steps = new[] { new PlacementStep { action = LivePlacement.PoseAction } };

            AssertRefused(steps, 1, "nœud manque");
        }

        [Test]
        public void BuildCircuit_WireWithAPinOfTheWrongLength_IsRefused()
        {
            var steps = new[]
            {
                Pose(0, "ENTREE"),
                Pose(1, "SORTIE"),
                new PlacementStep { action = LivePlacement.WireAction, de = new[] { 0 }, vers = new[] { 1, 0 } },
            };

            AssertRefused(steps, 3, "une broche s'écrit");
        }

        [Test]
        public void BuildCircuit_SameNodePosedTwice_IsRefused()
        {
            // Les règles du circuit s'appliquent aussi au rejeu : un identifiant est unique.
            var steps = new[] { Pose(0, "ENTREE"), Pose(0, "ENTREE") };

            AssertRefused(steps, 2, "deux fois");
        }

        [Test]
        public void BuildCircuit_WireToAPinThatDoesNotExist_IsRefused()
        {
            // Une entrée du circuit n'a pas de puits : on ne peut pas y câbler.
            var steps = new[] { Pose(0, "ENTREE"), Pose(1, "ENTREE"), Wire(0, 0, 1, 0) };

            AssertRefused(steps, 3, "broche");
        }
    }
}
