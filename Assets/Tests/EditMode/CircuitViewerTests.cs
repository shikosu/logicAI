using System.IO;
using NUnit.Framework;
using UnityEngine;

namespace LogicAI.Tests
{
    // Tests du visualiseur : la liste des fichiers, le choix d'un circuit, les erreurs.
    public class CircuitViewerTests
    {
        GameObject viewerObject;
        string temporaryFolder;

        [SetUp]
        public void SetUp()
        {
            viewerObject = new GameObject("TestViewer");
        }

        [TearDown]
        public void TearDown()
        {
            Object.DestroyImmediate(viewerObject);
            if (temporaryFolder != null && Directory.Exists(temporaryFolder)) Directory.Delete(temporaryFolder, true);
        }

        CircuitViewer NewViewer(string folder = "")
        {
            var viewer = viewerObject.AddComponent<CircuitViewer>();
            viewer.folder = folder;
            return viewer;
        }

        [Test]
        public void Refresh_ListsTheCircuitsFolderInAlphabeticalOrder()
        {
            // Règle vérifiée : cahier, plan de développement, phase 3 (Unity lit les fichiers
            // JSON) : les 31 fichiers du dossier circuits/, triés.
            CircuitViewer viewer = NewViewer();
            viewer.Refresh();

            Assert.AreEqual(31, viewer.Files.Count);
            Assert.IsNull(viewer.ErrorMessage);
            for (int i = 1; i < viewer.Files.Count; i++)
            {
                Assert.Less(string.CompareOrdinal(viewer.Files[i - 1], viewer.Files[i]), 0);
            }
        }

        [Test]
        public void Select_DrawsTheChosenCircuit()
        {
            // Règle vérifiée : cahier, « Côté Unity » (Dessin) : choisir un fichier dessine
            // son circuit, et un seul à la fois.
            CircuitViewer viewer = NewViewer();
            viewer.Refresh();
            int index = -1;
            for (int i = 0; i < viewer.Files.Count; i++)
            {
                if (Path.GetFileName(viewer.Files[i]) == "xor_A1_B0.json") index = i;
            }

            viewer.Select(index);

            Assert.AreEqual("xor_A1_B0", viewer.Current.nom);
            Assert.IsNull(viewer.ErrorMessage);
            Assert.IsNotNull(GameObject.Find("Circuit xor_A1_B0"));

            viewer.Select(0);   // un autre fichier : l'ancien dessin disparaît
            Assert.IsNull(GameObject.Find("Circuit xor_A1_B0"));
            Assert.IsNotNull(GameObject.Find("Circuit " + viewer.Current.nom));
        }

        [Test]
        public void Select_AnInvalidFile_KeepsTheErrorMessageAndDoesNotThrow()
        {
            // Règle vérifiée : CLAUDE.md (erreur claire, pas de plantage) : un fichier invalide
            // ne casse pas le visualiseur.
            temporaryFolder = Path.Combine(Path.GetTempPath(), "logicai_viewer_" + System.Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(temporaryFolder);
            File.WriteAllText(Path.Combine(temporaryFolder, "casse.json"), "{ ceci n'est pas un circuit }");
            CircuitViewer viewer = NewViewer(temporaryFolder);
            viewer.Refresh();

            viewer.Select(0);

            Assert.IsNull(viewer.Current);
            StringAssert.Contains("casse.json", viewer.ErrorMessage);
        }

        [Test]
        public void Refresh_MissingFolder_ReportsAnError()
        {
            // Règle vérifiée : CLAUDE.md (erreur claire).
            CircuitViewer viewer = NewViewer(Path.Combine(Path.GetTempPath(), "logicai_n_existe_pas"));
            viewer.Refresh();

            Assert.AreEqual(0, viewer.Files.Count);
            StringAssert.Contains("introuvable", viewer.ErrorMessage);
        }

        [Test]
        public void Refresh_EmptyFolder_ReportsThereIsNothingToShow()
        {
            temporaryFolder = Path.Combine(Path.GetTempPath(), "logicai_viewer_" + System.Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(temporaryFolder);
            CircuitViewer viewer = NewViewer(temporaryFolder);
            viewer.Refresh();

            Assert.AreEqual(0, viewer.Files.Count);
            StringAssert.Contains("aucun fichier", viewer.ErrorMessage);
        }

        [Test]
        public void Select_OutOfRange_ChangesNothing()
        {
            CircuitViewer viewer = NewViewer();
            viewer.Refresh();
            viewer.Select(0);
            string before = viewer.Current.nom;

            viewer.Select(-1);
            viewer.Select(viewer.Files.Count);

            Assert.AreEqual(before, viewer.Current.nom);
        }
    }
}
