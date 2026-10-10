using System.Collections;
using System.Net;
using System.Net.Sockets;
using System.Text;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

namespace LogicAI.Tests
{
    // Tests du mode « En direct » en mode Play : le vrai Update lit la liaison, et détruire le
    // visualiseur la ferme. Un petit serveur local (TcpListener) joue Python, sur un port libre
    // (jamais le 8765 : un vrai « python -m logicai.live » ne doit pas être dérangé).
    public class CircuitViewerLivePlayModeTests
    {
        const float WaitSeconds = 5f;

        // Copie de LiveSamples.CircuitLine (écrite par le vrai code Python) : l'assembly des tests
        // EditMode n'est pas visible depuis celui-ci. ' à la place de ".
        const string CircuitLine =
            "{'message':'circuit','circuit':{'nom':'essai','noeuds':[{'id':0,'type':'ENTREE','x':0,'y':0},{'id':1,'type':'NAND','x':2,'y':0},{'id':2,'type':'SORTIE','x':4,'y':0}],'cables':[{'de':[0,0],'vers':[1,0]},{'de':[0,0],'vers':[1,1]},{'de':[1,0],'vers':[2,0]}]}}";

        [UnityTest]
        public IEnumerator Update_ReadsTheLinesFromPython_AndDrawsThem()
        {
            // Règle vérifiée : cahier, phase 5 : l'essai envoyé par Python apparaît à l'écran sans
            // autre action que le clic sur « En direct » (ici EnterLiveMode).
            var listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            var viewerObject = new GameObject("LiveViewerForTest");
            TcpClient python = null;
            try
            {
                CircuitViewer viewer = viewerObject.AddComponent<CircuitViewer>();
                viewer.port = ((IPEndPoint)listener.LocalEndpoint).Port;
                yield return null;   // Start
                viewer.EnterLiveMode();

                float deadline = Time.realtimeSinceStartup + WaitSeconds;
                while (!listener.Pending() && Time.realtimeSinceStartup < deadline)
                {
                    yield return null;
                }
                Assert.IsTrue(listener.Pending(), "Unity ne s'est pas connecté");
                python = listener.AcceptTcpClient();
                byte[] bytes = Encoding.UTF8.GetBytes(CircuitLine.Replace('\'', '"') + "\n");
                python.GetStream().Write(bytes, 0, bytes.Length);

                deadline = Time.realtimeSinceStartup + WaitSeconds;
                while (viewer.Live.Shown == null && Time.realtimeSinceStartup < deadline)
                {
                    yield return null;
                }

                Assert.IsNotNull(viewer.Live.Shown, "le circuit envoyé n'est jamais arrivé");
                Assert.IsNotNull(GameObject.Find("Circuit essai"));
                Assert.AreEqual(0, viewer.RejectedLines);
            }
            finally
            {
                Object.Destroy(viewerObject);
                if (python != null) python.Close();
                listener.Stop();
            }
        }

        [UnityTest]
        public IEnumerator Destroy_ClosesTheConnection()
        {
            // Règle vérifiée : quitter le mode Play ne laisse pas de fil de connexion vivant.
            var listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            var viewerObject = new GameObject("LiveViewerForTest");
            TcpClient python = null;
            try
            {
                CircuitViewer viewer = viewerObject.AddComponent<CircuitViewer>();
                viewer.port = ((IPEndPoint)listener.LocalEndpoint).Port;
                yield return null;
                viewer.EnterLiveMode();

                float deadline = Time.realtimeSinceStartup + WaitSeconds;
                while (!listener.Pending() && Time.realtimeSinceStartup < deadline)
                {
                    yield return null;
                }
                Assert.IsTrue(listener.Pending(), "Unity ne s'est pas connecté");
                python = listener.AcceptTcpClient();

                Object.Destroy(viewerObject);
                yield return null;
                yield return null;

                bool closed = python.Client.Poll((int)(WaitSeconds * 1000000f), SelectMode.SelectRead) && python.Client.Available == 0;
                Assert.IsTrue(closed, "la connexion aurait dû être fermée à la destruction du visualiseur");
            }
            finally
            {
                if (viewerObject != null) Object.Destroy(viewerObject);
                if (python != null) python.Close();
                listener.Stop();
            }
        }

        [UnityTest]
        public IEnumerator TheAutomaticViewer_StartsInFilesMode_WithoutConnecting()
        {
            // Règle vérifiée : décision du plan de l'étape 9 : au démarrage du Play, le visualiseur
            // montre les fichiers et ne se connecte pas tout seul.
            yield return null;
            yield return null;

            CircuitViewer viewer = Object.FindFirstObjectByType<CircuitViewer>();

            Assert.IsNotNull(viewer);
            Assert.AreEqual(ViewerMode.Files, viewer.Mode);
            Assert.IsFalse(viewer.IsLiveConnected);
        }
    }
}
