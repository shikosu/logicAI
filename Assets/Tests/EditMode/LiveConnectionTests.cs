using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using NUnit.Framework;

namespace LogicAI.Tests
{
    // Tests de la connexion à Python. Un petit serveur local (TcpListener) joue le rôle de Python.
    // Ces tests attendent des événements réseau : ils bouclent jusqu'à une échéance au lieu
    // d'attendre un temps fixe, pour ne pas être instables sur une machine lente.
    // On n'utilise jamais le port par défaut (8765) : un vrai « python -m logicai.live » qui tourne
    // en même temps ne doit pas être dérangé.
    public class LiveConnectionTests
    {
        const int WaitMilliseconds = 5000;
        const int FastRetryMilliseconds = 50;

        // Le temps pendant lequel on vérifie qu'« il ne se passe rien ».
        const int QuietMilliseconds = 200;

        TcpListener listener;
        LiveConnection connection;
        readonly List<TcpClient> accepted = new List<TcpClient>();

        [SetUp]
        public void SetUp()
        {
            listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            connection = null;
        }

        [TearDown]
        public void TearDown()
        {
            if (connection != null)
            {
                connection.Stop();
            }
            foreach (TcpClient client in accepted)
            {
                client.Close();
            }
            accepted.Clear();
            listener.Stop();
        }

        int ListenerPort
        {
            get { return ((IPEndPoint)listener.LocalEndpoint).Port; }
        }

        // Un port où personne n'écoute (on en réserve un, puis on le libère).
        static int UnusedPort()
        {
            var probe = new TcpListener(IPAddress.Loopback, 0);
            probe.Start();
            int port = ((IPEndPoint)probe.LocalEndpoint).Port;
            probe.Stop();
            return port;
        }

        LiveConnection StartConnection(int port, int maxLineBytes = LiveConnection.DefaultMaxLineBytes)
        {
            connection = new LiveConnection(port, FastRetryMilliseconds, maxLineBytes);
            connection.Start();
            return connection;
        }

        static void WaitFor(Func<bool> condition, string what)
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

        // Accepte la connexion de Unity côté « Python ».
        TcpClient Accept()
        {
            WaitFor(() => listener.Pending(), "la connexion de Unity");
            TcpClient client = listener.AcceptTcpClient();
            accepted.Add(client);
            return client;
        }

        string NextLine()
        {
            string line = null;
            WaitFor(() => connection.TryDequeue(out line), "une ligne reçue");
            return line;
        }

        void AssertNoLine()
        {
            Thread.Sleep(QuietMilliseconds);
            string extra;
            Assert.IsFalse(connection.TryDequeue(out extra), "ligne inattendue : " + extra);
        }

        static void Send(TcpClient client, byte[] bytes)
        {
            NetworkStream stream = client.GetStream();
            stream.Write(bytes, 0, bytes.Length);
            stream.Flush();
        }

        static void SendText(TcpClient client, string text)
        {
            Send(client, Encoding.UTF8.GetBytes(text));
        }

        // Vrai si l'autre côté a coupé la connexion (Unity n'envoie rien : le seul motif de
        // lecture possible est la fermeture).
        static bool PeerClosed(TcpClient client)
        {
            return client.Client.Poll(WaitMilliseconds * 1000, SelectMode.SelectRead) && client.Client.Available == 0;
        }

        // --- Réception des lignes ---------------------------------------------------

        [Test]
        public void Lines_AreReceivedInOrder()
        {
            // Règle vérifiée : un message = une ligne ; Unity les lit dans l'ordre d'envoi.
            StartConnection(ListenerPort);
            TcpClient python = Accept();

            SendText(python, "un\ndeux\ntrois\n");

            Assert.AreEqual("un", NextLine());
            Assert.AreEqual("deux", NextLine());
            Assert.AreEqual("trois", NextLine());
            WaitFor(() => connection.IsConnected, "l'état « connecté »");
            Assert.IsNull(connection.LastError);
        }

        [Test]
        public void LineSplitAcrossPackets_IsDeliveredWhole()
        {
            // Règle vérifiée : une ligne n'est rendue qu'une fois complète (retour à la ligne reçu).
            StartConnection(ListenerPort);
            TcpClient python = Accept();

            SendText(python, "mor");
            AssertNoLine();
            SendText(python, "ceau\n");

            Assert.AreEqual("morceau", NextLine());
        }

        [Test]
        public void Utf8CharacterSplitAcrossPackets_IsDecodedCorrectly()
        {
            // Règle vérifiée : le texte est de l'UTF-8 ; « é » (2 octets) peut arriver coupé en deux.
            StartConnection(ListenerPort);
            TcpClient python = Accept();
            byte[] bytes = Encoding.UTF8.GetBytes("écrit\n");
            Assert.AreEqual((byte)0xC3, bytes[0], "hypothèse du test : « é » commence par l'octet 0xC3");
            var rest = new byte[bytes.Length - 1];
            Array.Copy(bytes, 1, rest, 0, rest.Length);

            Send(python, new[] { bytes[0] });
            AssertNoLine();
            Send(python, rest);

            Assert.AreEqual("écrit", NextLine());
        }

        [Test]
        public void BlankLines_AreIgnored()
        {
            StartConnection(ListenerPort);
            TcpClient python = Accept();

            SendText(python, "\n\nx\n\n");

            Assert.AreEqual("x", NextLine());
            AssertNoLine();
        }

        [Test]
        public void LineOfExactlyTheMaximumSize_IsAccepted()
        {
            StartConnection(ListenerPort, 100);
            TcpClient python = Accept();
            string line = new string('x', 100);

            SendText(python, line + "\n");

            Assert.AreEqual(line, NextLine());
        }

        [Test]
        public void LineOneByteTooLong_DropsTheConnection_AndNothingIsDelivered()
        {
            // Règle vérifiée : une ligne trop longue n'est jamais livrée, même en partie ;
            // la connexion est coupée puis rétablie, et la suite se lit normalement.
            StartConnection(ListenerPort, 100);
            TcpClient first = Accept();

            SendText(first, new string('x', 101));
            Assert.IsTrue(PeerClosed(first), "Unity aurait dû couper la connexion");
            TcpClient second = Accept();
            SendText(second, "ok\n");

            Assert.AreEqual("ok", NextLine());
            AssertNoLine();
        }

        // --- Connexion, coupure, reconnexion ------------------------------------------

        [Test]
        public void WithoutServer_IsNotConnected_AndReportsTheError()
        {
            StartConnection(UnusedPort());

            WaitFor(() => !string.IsNullOrEmpty(connection.LastError), "une erreur de connexion");

            Assert.IsFalse(connection.IsConnected);
        }

        [Test]
        public void ServerStartedAfterUnity_IsJoinedAutomatically()
        {
            // Règle vérifiée : on peut lancer Unity avant Python.
            int port = UnusedPort();
            StartConnection(port);
            WaitFor(() => !string.IsNullOrEmpty(connection.LastError), "un premier essai raté");
            Assert.IsFalse(connection.IsConnected);

            listener.Stop();
            listener = new TcpListener(IPAddress.Loopback, port);
            listener.Start();
            TcpClient python = Accept();
            SendText(python, "tard\n");

            Assert.AreEqual("tard", NextLine());
            WaitFor(() => connection.IsConnected, "l'état « connecté »");
            Assert.IsNull(connection.LastError);
        }

        [Test]
        public void ServerThatDrops_IsReconnected()
        {
            // Règle vérifiée : si Python s'arrête puis revient, Unity se reconnecte tout seul.
            StartConnection(ListenerPort);
            TcpClient first = Accept();
            SendText(first, "avant\n");
            Assert.AreEqual("avant", NextLine());

            first.Close();
            TcpClient second = Accept();
            SendText(second, "apres\n");

            Assert.AreEqual("apres", NextLine());
        }

        [Test]
        public void Start_Twice_KeepsASingleConnection()
        {
            StartConnection(ListenerPort);
            connection.Start();
            Accept();

            Thread.Sleep(QuietMilliseconds);

            Assert.IsFalse(listener.Pending(), "une 2e connexion a été ouverte");
        }

        // --- Arrêt propre ----------------------------------------------------------------

        [Test]
        public void Stop_ClosesTheConnection()
        {
            StartConnection(ListenerPort);
            TcpClient python = Accept();
            WaitFor(() => connection.IsConnected, "l'état « connecté »");

            connection.Stop();

            Assert.IsFalse(connection.IsConnected);
            Assert.IsTrue(PeerClosed(python), "la connexion aurait dû être fermée");
        }

        [Test]
        public void Dispose_StopsTheConnection()
        {
            StartConnection(ListenerPort);
            TcpClient python = Accept();

            connection.Dispose();

            Assert.IsTrue(PeerClosed(python), "la connexion aurait dû être fermée");
        }

        [Test]
        public void Stop_WhileWaitingToRetry_ReturnsQuickly()
        {
            // Règle vérifiée : l'arrêt n'attend pas la fin du délai entre deux essais.
            connection = new LiveConnection(UnusedPort(), 10000);
            connection.Start();
            WaitFor(() => !string.IsNullOrEmpty(connection.LastError), "un premier essai raté");

            var watch = Stopwatch.StartNew();
            connection.Stop();

            Assert.IsTrue(watch.ElapsedMilliseconds < 1000, "Stop() a duré " + watch.ElapsedMilliseconds + " ms");
        }

        [Test]
        public void Stop_WithoutStart_DoesNothing()
        {
            connection = new LiveConnection(UnusedPort());

            connection.Stop();

            Assert.IsFalse(connection.IsConnected);
        }

        [Test]
        public void Stop_Twice_DoesNothing()
        {
            StartConnection(ListenerPort);
            Accept();

            connection.Stop();
            connection.Stop();

            Assert.IsFalse(connection.IsConnected);
        }

        [Test]
        public void Start_AfterStop_ConnectsAgain()
        {
            StartConnection(ListenerPort);
            Accept();
            connection.Stop();

            connection.Start();
            TcpClient python = Accept();
            SendText(python, "retour\n");

            Assert.AreEqual("retour", NextLine());
        }

        // --- Réglages refusés ------------------------------------------------------------

        [Test]
        public void Constructor_RefusesInvalidSettings()
        {
            Assert.Throws<ArgumentOutOfRangeException>(() => new LiveConnection(0));
            Assert.Throws<ArgumentOutOfRangeException>(() => new LiveConnection(65536));
            Assert.Throws<ArgumentOutOfRangeException>(() => new LiveConnection(8765, 0));
            Assert.Throws<ArgumentOutOfRangeException>(() => new LiveConnection(8765, 1000, 0));
        }

        [Test]
        public void Constructor_AcceptsThePortLimits()
        {
            Assert.DoesNotThrow(() => new LiveConnection(1));
            Assert.DoesNotThrow(() => new LiveConnection(65535));
        }
    }
}
