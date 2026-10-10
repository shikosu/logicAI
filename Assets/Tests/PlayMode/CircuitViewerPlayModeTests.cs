using System.Collections;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

namespace LogicAI.Tests
{
    // Tests du visualiseur en mode Play : ce que l'on voit réellement au lancement.
    public class CircuitViewerPlayModeTests
    {
        [UnityTest]
        public IEnumerator Bootstrap_StartsTheViewerAndDrawsTheFirstCircuit()
        {
            // Règle vérifiée : décision du plan de la phase 3 (le visualiseur démarre tout seul
            // au lancement du Play, sans modifier la scène) : le premier circuit de la liste
            // est dessiné.
            yield return null;
            yield return null;   // laisse Start s'exécuter

            CircuitViewer viewer = Object.FindFirstObjectByType<CircuitViewer>();

            Assert.IsNotNull(viewer, "le visualiseur n'a pas démarré tout seul");
            Assert.AreEqual(31, viewer.Files.Count);
            Assert.IsNotNull(viewer.Current);
            Assert.IsNull(viewer.ErrorMessage);
            Assert.IsNotNull(GameObject.Find("Circuit " + viewer.Current.nom));
        }

        [UnityTest]
        public IEnumerator Select_FitsTheMainCameraSoThatTheWholeCircuitIsVisible()
        {
            // Règle vérifiée : décision du plan de la phase 3 (la caméra est cadrée sur le
            // circuit, à droite de la liste) : tous les nœuds sont dans le champ de la caméra.
            var cameraObject = new GameObject("MainCameraForTest");
            cameraObject.tag = "MainCamera";
            Camera camera = cameraObject.AddComponent<Camera>();
            camera.transform.position = new Vector3(0f, 0f, -10f);
            var viewerObject = new GameObject("ViewerForTest");
            CircuitViewer viewer = viewerObject.AddComponent<CircuitViewer>();
            yield return null;   // Start : Refresh puis Select(0)

            viewer.Select(viewer.Files.Count - 1);   // xor_A1_B1 : le plus grand circuit
            yield return null;

            Assert.IsTrue(camera.orthographic);
            Assert.Greater(camera.rect.x, 0f, "la caméra doit laisser la place à la liste");
            Assert.Less(camera.rect.x, 1f);
            foreach (NodeData node in viewer.Current.noeuds)
            {
                Vector3 view = camera.WorldToViewportPoint(CircuitGeometry.Center(node));
                Assert.That(view.x, Is.InRange(0f, 1f), "nœud " + node.id + " hors du champ en x");
                Assert.That(view.y, Is.InRange(0f, 1f), "nœud " + node.id + " hors du champ en y");
            }

            Object.Destroy(viewerObject);
            Object.Destroy(cameraObject);
        }
    }
}
