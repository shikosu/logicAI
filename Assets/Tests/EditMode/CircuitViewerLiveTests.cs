using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using NUnit.Framework;
using UnityEngine;

namespace LogicAI.Tests
{
    // Tests du visualiseur en mode « En direct » : un petit serveur local (TcpListener) joue Python.
    // Les tests jouent les images à la main avec viewer.Tick (Update ne tourne pas en EditMode).
    // On n'utilise jamais le port par défaut (8765) : un vrai « python -m logicai.live » qui tourne
    // en même temps ne doit pas être dérangé.
    public class CircuitViewerLiveTests
    {
        const int WaitMilliseconds = 5000;

        TcpListener listener;
        GameObject viewerObject;
        CircuitViewer viewer;
        readonly List<TcpClient> accepted = new List<TcpClient>();

        [SetUp]
        public void SetUp()
        {
            listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            viewerObject = new GameObject("TestLiveViewer");
            viewer = viewerObject.AddComponent<CircuitViewer>();
            viewer.port = ((IPEndPoint)listener.LocalEndpoint).Port;
        }

        [TearDown]
        public void TearDown()
        {
            // OnDestroy ne s'exécute pas en EditMode : on coupe la liaison nous-mêmes, sinon le fil de
            // connexion resterait vivant et pourrait se brancher sur le serveur d'un autre test.
            viewer.EnterFilesMode();
            Object.DestroyImmediate(viewerObject);
            DestroyDrawnCircuits();
            foreach (TcpClient client in accepted)
            {
                client.Close();
            }
            accepted.Clear();
            listener.Stop();
        }

        // Efface les dessins laissés dans la scène (les circuits sont des objets à la racine).
        static void DestroyDrawnCircuits()
        {
            foreach (Transform transform in Object.FindObjectsByType<Transform>(FindObjectsSortMode.None))
            {
                if (transform != null && transform.parent == null && transform.name.StartsWith("Circuit "))
                {
                    Object.DestroyImmediate(transform.gameObject);
                }
            }
        }

        // Le nombre de dessins à la racine de la scène qui portent ce nom.
        static int DrawnCount(string name)
        {
            int count = 0;
            foreach (Transform transform in Object.FindObjectsByType<Transform>(FindObjectsSortMode.None))
            {
                if (transform.parent == null && transform.name == name)
                {
                    count++;
                }
            }
            return count;
        }

        static int UnusedPort()
        {
            var probe = new TcpListener(IPAddress.Loopback, 0);
            probe.Start();
            int port = ((IPEndPoint)probe.LocalEndpoint).Port;
            probe.Stop();
            return port;
        }

        static void WaitFor(System.Func<bool> condition, string what)
        {
            var watch = Stopwatch.StartNew();
            while (!condition())
            {
                if (watch.ElapsedMilliseconds > WaitMilliseconds)
                {
                    Assert.Fail("Délai dépassé en attendant : " + what);
                }
                Thread.Sleep(5);
            }
        }

        // Joue des images du visualiseur (Tick) jusqu'à ce que la condition soit vraie.
        void PumpUntil(System.Func<bool> condition, string what)
        {
            WaitFor(() =>
            {
                viewer.Tick(0f);
                return condition();
            }, what);
        }

        TcpClient Accept()
        {
            WaitFor(() => listener.Pending(), "la connexion de Unity");
            TcpClient client = listener.AcceptTcpClient();
            accepted.Add(client);
            return client;
        }

        // Envoie un message (un échantillon de LiveSamples) sous forme d'une ligne.
        static void SendLine(TcpClient python, string sample)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(LiveSamples.Json(sample) + "\n");
            NetworkStream stream = python.GetStream();
            stream.Write(bytes, 0, bytes.Length);
            stream.Flush();
        }

        static void SendRaw(TcpClient python, string text)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(text);
            NetworkStream stream = python.GetStream();
            stream.Write(bytes, 0, bytes.Length);
            stream.Flush();
        }

        static bool PeerClosed(TcpClient client)
        {
            return client.Client.Poll(WaitMilliseconds * 1000, SelectMode.SelectRead) && client.Client.Available == 0;
        }

        // --- Démarrage et changement de mode ---------------------------------------------

        [Test]
        public void NewViewer_IsInFilesMode_AndNotConnected()
        {
            // Règle vérifiée : décision du plan de l'étape 9 : le visualiseur démarre comme en phase 3
            // et ne se connecte pas tout seul (il volerait la liaison d'un autre Unity).
            Assert.AreEqual(ViewerMode.Files, viewer.Mode);
            Assert.IsFalse(viewer.IsLiveConnected);
            Assert.AreEqual("", viewer.ConnectionText);
            Assert.IsFalse(listener.Pending());
        }

        [Test]
        public void EnterLiveMode_ConnectsToPython()
        {
            viewer.EnterLiveMode();
            Accept();

            WaitFor(() => viewer.IsLiveConnected, "l'état « connecté »");

            Assert.AreEqual(ViewerMode.Live, viewer.Mode);
            Assert.AreEqual("Connecté à Python", viewer.ConnectionText);
        }

        [Test]
        public void EnterLiveMode_Twice_KeepsASingleConnection()
        {
            viewer.EnterLiveMode();
            viewer.EnterLiveMode();
            Accept();

            Thread.Sleep(300);

            Assert.IsFalse(listener.Pending(), "une 2e connexion a été ouverte");
        }

        [Test]
        public void EnterLiveMode_ErasesTheFileDrawing()
        {
            viewer.Refresh();
            viewer.Select(0);
            string drawnName = "Circuit " + viewer.Current.nom;
            Assert.IsNotNull(GameObject.Find(drawnName));

            viewer.EnterLiveMode();

            Assert.IsNull(GameObject.Find(drawnName));
        }

        [Test]
        public void WithoutPython_TheViewerSaysSo()
        {
            viewer.port = UnusedPort();

            viewer.EnterLiveMode();

            Assert.IsFalse(viewer.IsLiveConnected);
            StringAssert.Contains("Python ne répond pas", viewer.ConnectionText);
            StringAssert.Contains("127.0.0.1:" + viewer.port, viewer.ConnectionText);
        }

        [Test]
        public void EnterLiveMode_WithAnInvalidPort_ChangesNothing()
        {
            viewer.port = 0;

            Assert.Throws<System.ArgumentOutOfRangeException>(() => viewer.EnterLiveMode());

            Assert.AreEqual(ViewerMode.Files, viewer.Mode);
            Assert.IsFalse(viewer.IsLiveConnected);
        }

        [Test]
        public void EnterFilesMode_StopsTheConnection_AndDrawsTheFileAgain()
        {
            viewer.Refresh();
            viewer.Select(0);
            string drawnName = "Circuit " + viewer.Current.nom;
            viewer.EnterLiveMode();
            TcpClient python = Accept();
            WaitFor(() => viewer.IsLiveConnected, "l'état « connecté »");

            viewer.EnterFilesMode();

            Assert.AreEqual(ViewerMode.Files, viewer.Mode);
            Assert.IsFalse(viewer.IsLiveConnected);
            Assert.IsTrue(PeerClosed(python), "la connexion aurait dû être fermée");
            Assert.IsNotNull(GameObject.Find(drawnName), "le circuit du fichier doit être redessiné");
        }

        // --- Ce que Python envoie est dessiné -----------------------------------------------

        [Test]
        public void Circuit_FromPython_IsDrawn_AndReplacedByTheNextFrame()
        {
            // Règle vérifiée : cahier, phase 5 : « on regarde l'IA construire » : l'essai envoyé par
            // Python est dessiné, et chaque image de valeurs remplace le dessin précédent.
            viewer.EnterLiveMode();
            TcpClient python = Accept();

            SendLine(python, LiveSamples.CircuitLine);
            PumpUntil(() => viewer.Live.Shown != null, "le circuit");
            Assert.AreEqual(1, DrawnCount("Circuit essai"));

            SendLine(python, LiveSamples.StateLine);
            PumpUntil(() => CircuitLoader.HasState(viewer.Live.Shown), "les valeurs");

            Assert.AreEqual(1, DrawnCount("Circuit essai"), "l'ancien dessin doit avoir été remplacé");
            Assert.AreEqual("essai en direct - top 1 - stable", viewer.Live.Caption);
        }

        [Test]
        public void UnreadableLine_IsCounted_AndDoesNotStopTheViewer()
        {
            // Règle vérifiée : CLAUDE.md (erreur claire, pas de plantage).
            viewer.EnterLiveMode();
            TcpClient python = Accept();

            SendRaw(python, "ceci n'est pas du JSON\n");
            SendLine(python, LiveSamples.CircuitLine);
            PumpUntil(() => viewer.Live.Shown != null, "le circuit après la ligne illisible");

            Assert.AreEqual(1, viewer.RejectedLines);
            Assert.IsFalse(string.IsNullOrEmpty(viewer.LastLineError));
            Assert.AreEqual(1, DrawnCount("Circuit essai"));
        }

        [Test]
        public void Discovery_JoinsTheLibrary_AndTheReplayIsDrawnPieceByPiece()
        {
            viewer.EnterLiveMode();
            TcpClient python = Accept();
            SendLine(python, LiveSamples.NotDiscoveryLine);
            PumpUntil(() => viewer.Live.Discoveries.Count == 1, "la découverte");
            Assert.AreEqual(0, DrawnCount("Circuit NOT"), "une découverte ne se dessine que rediffusée");

            viewer.Live.StartReplay(0);
            viewer.Tick(LiveModel.ReplayStepSeconds * 2f);

            Assert.AreEqual(2, viewer.Live.ReplayStep);
            Assert.AreEqual(1, DrawnCount("Circuit NOT"));

            viewer.Live.Restart();
            viewer.Tick(0f);

            Assert.AreEqual(0, DrawnCount("Circuit NOT"), "au début de la rediffusion, rien n'est posé");
        }

        [Test]
        public void Tick_WithAVeryLongFrame_DoesNotMakeTheReplayJump()
        {
            // Règle vérifiée : une image très longue (fenêtre en pause) ne fait pas sauter la rediffusion
            // jusqu'à la fin : le temps d'une image est limité à une seconde (2 pièces à 0,4 s chacune).
            viewer.EnterLiveMode();
            TcpClient python = Accept();
            SendLine(python, LiveSamples.NotDiscoveryLine);
            PumpUntil(() => viewer.Live.Discoveries.Count == 1, "la découverte");
            viewer.Live.StartReplay(0);

            viewer.Tick(100f);

            Assert.AreEqual(2, viewer.Live.ReplayStep);
        }

        // --- Python relancé, Python arrêté -------------------------------------------------

        [Test]
        public void NewPythonSession_ClearsTheOldLibrary()
        {
            // Règle vérifiée : à chaque connexion Python renvoie son historique ; une nouvelle session
            // (Python relancé) ne doit pas garder les découvertes de l'ancienne.
            viewer.EnterLiveMode();
            TcpClient first = Accept();
            SendLine(first, LiveSamples.NotDiscoveryLine);
            PumpUntil(() => viewer.Live.Discoveries.Count == 1, "la découverte de la 1re session");

            first.Close();
            TcpClient second = Accept();
            SendLine(second, LiveSamples.XorDiscoveryLine);

            PumpUntil(
                () => viewer.Live.Discoveries.Count == 1 && viewer.Live.Discoveries[0].nom == "XOR",
                "la bibliothèque de la 2e session seule");
        }

        [Test]
        public void WhenPythonStops_TheLastPictureStays_AndTheViewerRetries()
        {
            viewer.EnterLiveMode();
            TcpClient python = Accept();
            SendLine(python, LiveSamples.CircuitLine);
            PumpUntil(() => viewer.Live.Shown != null, "le circuit");

            python.Close();
            PumpUntil(() => !viewer.IsLiveConnected, "la coupure");

            Assert.AreEqual(1, DrawnCount("Circuit essai"), "le dernier dessin reste affiché");
            StringAssert.Contains("Python ne répond pas", viewer.ConnectionText);
        }
    }
}
