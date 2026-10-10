using System.IO;
using NUnit.Framework;
using UnityEngine;

namespace LogicAI.Tests
{
    // Tests de la lecture des fichiers de circuit.
    public class CircuitLoaderTests
    {
        // Pour écrire du JSON dans du C# sans doubler les guillemets : ' devient ".
        static string Json(string text)
        {
            return text.Replace('\'', '"');
        }

        // L'exemple du cahier : un NOT fait d'une seule NAND, avec les positions x et y.
        const string CahierExample =
            "{'nom': 'NOT',"
            + "'noeuds': [{'id': 0, 'type': 'ENTREE', 'x': 0, 'y': 0},"
            + "{'id': 1, 'type': 'NAND', 'x': 2, 'y': 0},"
            + "{'id': 2, 'type': 'SORTIE', 'x': 4, 'y': 0}],"
            + "'cables': [{'de': [0, 0], 'vers': [1, 0]},"
            + "{'de': [0, 0], 'vers': [1, 1]},"
            + "{'de': [1, 0], 'vers': [2, 0]}]}";

        static string ProjectCircuitsFolder()
        {
            return Path.GetFullPath(Path.Combine(Application.dataPath, "..", "circuits"));
        }

        // --- Lecture d'un fichier valide --------------------------------------------

        [Test]
        public void Parse_CahierExample_ReadsNodesWiresAndPositions()
        {
            // Règle vérifiée : cahier, « Exemple de circuit en JSON ».
            CircuitFile file = CircuitLoader.Parse(Json(CahierExample));

            Assert.AreEqual("NOT", file.nom);
            Assert.AreEqual(3, file.noeuds.Length);
            Assert.AreEqual("NAND", file.noeuds[1].type);
            Assert.AreEqual(2, file.noeuds[1].x);
            Assert.AreEqual(4, file.noeuds[2].x);
            Assert.AreEqual(3, file.cables.Length);
            CollectionAssert.AreEqual(new[] { 0, 0 }, file.cables[1].de);
            CollectionAssert.AreEqual(new[] { 1, 1 }, file.cables[1].vers);
            Assert.AreEqual(NodeKind.Input, CircuitLoader.KindOf(file.noeuds[0]));
            Assert.AreEqual(NodeKind.Output, CircuitLoader.KindOf(file.noeuds[2]));
            Assert.IsFalse(CircuitLoader.HasState(file));
        }

        [Test]
        public void Parse_WithState_ReadsTopStabilityAndValues()
        {
            // Règle vérifiée : cahier, message « etat » (les valeurs 0/1 de chaque fil à un
            // top donné).
            string json = CahierExample.Substring(0, CahierExample.Length - 1)
                + ",'etat': {'top': 2, 'stable': true, 'noeuds': [0, 1, 1], 'cables': [0, 0, 1]}}";

            CircuitFile file = CircuitLoader.Parse(Json(json));

            Assert.IsTrue(CircuitLoader.HasState(file));
            Assert.AreEqual(2, file.etat.top);
            Assert.IsTrue(file.etat.stable);
            CollectionAssert.AreEqual(new[] { 0, 1, 1 }, file.etat.noeuds);
            CollectionAssert.AreEqual(new[] { 0, 0, 1 }, file.etat.cables);
        }

        [Test]
        public void Parse_UnstableState_IsReadAsNotStable()
        {
            // Règle vérifiée : cahier, « Les trois cas détectés » (instable).
            string json = CahierExample.Substring(0, CahierExample.Length - 1)
                + ",'etat': {'top': 1, 'stable': false, 'noeuds': [0, 1, 1], 'cables': [0, 0, 1]}}";

            Assert.IsFalse(CircuitLoader.Parse(Json(json)).etat.stable);
        }

        [Test]
        public void Parse_ComponentNode_ReadsNameAndPinCounts()
        {
            // Règle vérifiée : décision du plan de la phase 2 (type COMPOSANT avec ref,
            // entrees et sorties). « ref » est un mot réservé de C# : le champ s'écrit @ref.
            string json = "{'nom': 'TOP', 'noeuds': ["
                + "{'id': 0, 'type': 'COMPOSANT', 'x': 2, 'y': 0, 'ref': 'XOR', 'entrees': 2, 'sorties': 1}],"
                + "'cables': []}";

            CircuitFile file = CircuitLoader.Parse(Json(json));

            Assert.AreEqual(NodeKind.Component, CircuitLoader.KindOf(file.noeuds[0]));
            Assert.AreEqual("XOR", file.noeuds[0].@ref);
            Assert.AreEqual(2, CircuitGeometry.SinkCount(file.noeuds[0]));
            Assert.AreEqual(1, CircuitGeometry.SourceCount(file.noeuds[0]));
        }

        [Test]
        public void Parse_EmptyCircuitWithAState_HasAState()
        {
            // Règle vérifiée : cahier, message « etat » : un état sans nœud ni câble reste un état.
            CircuitFile file = CircuitLoader.Parse(Json(
                "{'nom': 'VIDE', 'noeuds': [], 'cables': [],"
                + "'etat': {'top': 1, 'stable': true, 'noeuds': [], 'cables': []}}"));
            Assert.IsTrue(CircuitLoader.HasState(file));
        }

        [Test]
        public void Parse_EmptyCircuit_IsAccepted()
        {
            // Règle vérifiée : prompt phase 1, section A (un circuit peut être vide).
            CircuitFile file = CircuitLoader.Parse(Json("{'nom': 'VIDE', 'noeuds': [], 'cables': []}"));
            Assert.AreEqual(0, file.noeuds.Length);
        }

        // --- Le contrat avec Python : les fichiers qu'il écrit ----------------------

        [Test]
        public void Load_AllFilesWrittenByPython_AreReadWithTheirState()
        {
            // Règle vérifiée : cahier, plan de développement, phase 3 (Unity lit un fichier
            // JSON : ici les 31 fichiers d'exemples écrits par Python dans circuits/).
            string[] paths = Directory.GetFiles(ProjectCircuitsFolder(), "*.json");

            Assert.AreEqual(31, paths.Length, "dossier circuits/ : " + ProjectCircuitsFolder());
            foreach (string path in paths)
            {
                CircuitFile file = CircuitLoader.Load(path);
                Assert.AreEqual(Path.GetFileNameWithoutExtension(path), file.nom);
                Assert.IsTrue(CircuitLoader.HasState(file), path);
            }
        }

        [Test]
        public void Load_XorWithA1AndB0_HasTheValuesComputedByPython()
        {
            // Règle vérifiée : cahier, message « etat ». Valeurs calculées à la main dans les
            // tests Python (test_snapshot.py) : A, B, n1, n2, n3, n4, sortie.
            CircuitFile file = CircuitLoader.Load(Path.Combine(ProjectCircuitsFolder(), "xor_A1_B0.json"));

            CollectionAssert.AreEqual(new[] { 1, 0, 1, 0, 1, 1, 1 }, file.etat.noeuds);
            CollectionAssert.AreEqual(new[] { 1, 0, 1, 1, 0, 1, 0, 1, 1 }, file.etat.cables);
            Assert.IsTrue(file.etat.stable);
            Assert.AreEqual(4, file.etat.top);
        }

        // --- Fichiers invalides ------------------------------------------------------

        void AssertRefused(string json, string expectedPart)
        {
            var exception = Assert.Throws<CircuitFormatException>(() => CircuitLoader.Parse(Json(json)));
            StringAssert.Contains(expectedPart, exception.Message);
        }

        [Test]
        public void Parse_Empty_IsRefused()
        {
            AssertRefused("   ", "vide");
        }

        [Test]
        public void Parse_NotJson_IsRefused()
        {
            AssertRefused("ceci n'est pas du JSON", "JSON");
        }

        [Test]
        public void Parse_WithoutName_IsRefused()
        {
            AssertRefused("{'noeuds': [], 'cables': []}", "nom");
        }

        [Test]
        public void Parse_UnknownNodeType_IsRefused()
        {
            AssertRefused("{'nom': 'X', 'noeuds': [{'id': 0, 'type': 'PORTE'}], 'cables': []}", "PORTE");
        }

        [Test]
        public void Parse_NodeWithoutType_IsRefused()
        {
            AssertRefused("{'nom': 'X', 'noeuds': [{'id': 0}], 'cables': []}", "type");
        }

        [Test]
        public void Parse_DuplicateIdentifier_IsRefused()
        {
            AssertRefused(
                "{'nom': 'X', 'noeuds': [{'id': 0, 'type': 'NAND'}, {'id': 0, 'type': 'NAND'}], 'cables': []}",
                "deux fois");
        }

        [Test]
        public void Parse_ComponentWithoutName_IsRefused()
        {
            AssertRefused(
                "{'nom': 'X', 'noeuds': [{'id': 0, 'type': 'COMPOSANT', 'entrees': 1, 'sorties': 1}], 'cables': []}",
                "ref");
        }

        [Test]
        public void Parse_ComponentWithNegativePins_IsRefused()
        {
            AssertRefused(
                "{'nom': 'X', 'noeuds': [{'id': 0, 'type': 'COMPOSANT', 'ref': 'A', 'entrees': -1, 'sorties': 1}], 'cables': []}",
                "négatif");
        }

        [Test]
        public void Parse_WireToUnknownNode_IsRefused()
        {
            AssertRefused(
                "{'nom': 'X', 'noeuds': [{'id': 0, 'type': 'ENTREE'}], 'cables': [{'de': [0, 0], 'vers': [9, 0]}]}",
                "n'existe pas");
        }

        [Test]
        public void Parse_WireFromAPinThatDoesNotExist_IsRefused()
        {
            // Une NAND n'a qu'une source (index 0) : l'index 1 n'existe pas comme source.
            AssertRefused(
                "{'nom': 'X', 'noeuds': [{'id': 0, 'type': 'NAND'}, {'id': 1, 'type': 'SORTIE'}],"
                + "'cables': [{'de': [0, 1], 'vers': [1, 0]}]}",
                "broche");
        }

        [Test]
        public void Parse_WireToAPinOfTheWrongKind_IsRefused()
        {
            // Une ENTREE n'a pas de puits : on ne peut pas y brancher un câble.
            AssertRefused(
                "{'nom': 'X', 'noeuds': [{'id': 0, 'type': 'NAND'}, {'id': 1, 'type': 'ENTREE'}],"
                + "'cables': [{'de': [0, 0], 'vers': [1, 0]}]}",
                "broche");
        }

        [Test]
        public void Parse_PinWithTheWrongLength_IsRefused()
        {
            AssertRefused(
                "{'nom': 'X', 'noeuds': [{'id': 0, 'type': 'NAND'}], 'cables': [{'de': [0], 'vers': [0, 0]}]}",
                "[nœud, index]");
        }

        [Test]
        public void Parse_StateOfTheWrongSize_IsRefused()
        {
            string json = CahierExample.Substring(0, CahierExample.Length - 1)
                + ",'etat': {'top': 2, 'stable': true, 'noeuds': [0, 1], 'cables': [0, 0, 1]}}";
            AssertRefused(json, "etat");
        }

        [Test]
        public void Load_MissingFile_IsRefused()
        {
            var exception = Assert.Throws<CircuitFormatException>(
                () => CircuitLoader.Load(Path.Combine(ProjectCircuitsFolder(), "n_existe_pas.json")));
            StringAssert.Contains("n_existe_pas.json", exception.Message);
        }
    }
}
