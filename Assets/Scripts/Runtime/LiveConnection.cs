using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;

namespace LogicAI
{
    // La connexion à Python (python/src/logicai/live_server.py) : Python écoute sur 127.0.0.1,
    // Unity se connecte. Un fil séparé lit le socket (une lecture peut durer : elle ne doit pas
    // figer l'affichage) et dépose chaque ligne reçue dans une file. Le fil principal de Unity
    // vide cette file avec TryDequeue, dans Update : la scène ne se modifie que depuis lui.
    // Les lignes sont rendues brutes ; c'est LiveMessageParser qui les lit.
    //
    //   fil de lecture  --lignes-->  [ ConcurrentQueue ]  --TryDequeue-->  Update (fil principal)
    //
    // Si Python n'est pas lancé, ou s'arrête, la connexion est retentée toutes les secondes :
    // on peut donc lancer Unity avant ou après Python.
    public class LiveConnection : IDisposable
    {
        public const int DefaultPort = 8765;
        public const int DefaultRetryMilliseconds = 1000;

        // Une ligne plus longue est refusée : la connexion est coupée puis retentée.
        public const int DefaultMaxLineBytes = 4 * 1024 * 1024;

        const byte NewLine = (byte)'\n';
        const int MinPort = 1;
        const int MaxPort = 65535;
        const int ChunkBytes = 64 * 1024;

        // Le fil regarde s'il doit s'arrêter au moins toutes les 100 ms.
        const int PollMicroseconds = 100000;
        const int StopTimeoutMilliseconds = 2000;

        // Une ligne reçue, avec le numéro de la connexion qui l'a apportée (1 pour la première).
        struct ReceivedLine
        {
            public int Connection;
            public string Text;
        }

        readonly int port;
        readonly int retryMilliseconds;
        readonly int maxLineBytes;
        readonly ConcurrentQueue<ReceivedLine> lines = new ConcurrentQueue<ReceivedLine>();
        readonly object gate = new object();

        Thread thread;
        ManualResetEvent stopSignal;
        Socket current;
        volatile bool connected;
        volatile string lastError;
        volatile int connectionCount;

        public LiveConnection(int port = DefaultPort, int retryMilliseconds = DefaultRetryMilliseconds, int maxLineBytes = DefaultMaxLineBytes)
        {
            if (port < MinPort || port > MaxPort)
            {
                throw new ArgumentOutOfRangeException("port", port, "le port doit être entre " + MinPort + " et " + MaxPort + ".");
            }
            if (retryMilliseconds <= 0)
            {
                throw new ArgumentOutOfRangeException("retryMilliseconds", retryMilliseconds, "le délai entre deux essais doit être positif.");
            }
            if (maxLineBytes <= 0)
            {
                throw new ArgumentOutOfRangeException("maxLineBytes", maxLineBytes, "la taille maximale d'une ligne doit être positive.");
            }
            this.port = port;
            this.retryMilliseconds = retryMilliseconds;
            this.maxLineBytes = maxLineBytes;
        }

        // Vrai tant qu'on est connecté à Python.
        public bool IsConnected
        {
            get { return connected; }
        }

        // Le nombre de connexions réussies depuis le début (0 avant la première).
        public int ConnectionCount
        {
            get { return connectionCount; }
        }

        // La raison du dernier échec de connexion (nulle quand on est connecté ou avant le
        // premier essai). Pour l'interface : « Python ne répond pas ».
        public string LastError
        {
            get { return lastError; }
        }

        // Lance le fil de connexion. Sans effet s'il tourne déjà.
        public void Start()
        {
            lock (gate)
            {
                if (thread != null)
                {
                    return;
                }
                ManualResetEvent signal = new ManualResetEvent(false);
                stopSignal = signal;
                thread = new Thread(() => Run(signal)) { IsBackground = true, Name = "LiveConnection" };
                thread.Start();
            }
        }

        // Arrête le fil et ferme la connexion. Sans effet si rien ne tourne ; on peut rappeler Start ensuite.
        public void Stop()
        {
            Thread toJoin;
            ManualResetEvent signal;
            lock (gate)
            {
                if (thread == null)
                {
                    return;
                }
                toJoin = thread;
                signal = stopSignal;
                thread = null;
                stopSignal = null;
                signal.Set();
                if (current != null)
                {
                    current.Close();
                }
            }
            if (toJoin.Join(StopTimeoutMilliseconds))
            {
                signal.Close();
            }
            connected = false;
        }

        public void Dispose()
        {
            Stop();
        }

        // Rend la prochaine ligne reçue (sans le retour à la ligne), ou faux s'il n'y en a pas.
        public bool TryDequeue(out string line)
        {
            int connection;
            return TryDequeue(out line, out connection);
        }

        // Pareil, avec le numéro de la connexion qui a apporté la ligne. Quand ce numéro change, Python
        // a été relancé (ou la liaison a été coupée) : les lignes qui suivent viennent d'une nouvelle session.
        // Le fil de lecture est seul à le fixer : l'ordre est exact, même si Unity ne lit la file qu'après coup.
        public bool TryDequeue(out string line, out int connection)
        {
            ReceivedLine received;
            if (lines.TryDequeue(out received))
            {
                line = received.Text;
                connection = received.Connection;
                return true;
            }
            line = null;
            connection = 0;
            return false;
        }

        // Le fil : se connecte, lit jusqu'à la coupure, attend, recommence, jusqu'à l'arrêt.
        void Run(ManualResetEvent signal)
        {
            while (!signal.WaitOne(0))
            {
                Socket socket = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
                try
                {
                    if (!Register(socket, signal))
                    {
                        return;
                    }
                    socket.Connect(IPAddress.Loopback, port);
                    connectionCount++;
                    lastError = null;
                    connected = true;
                    ReadLines(socket, signal);
                }
                catch (SocketException exception)
                {
                    lastError = exception.Message;
                }
                catch (ObjectDisposedException)
                {
                    // Stop() a fermé la connexion pendant qu'on la lisait : c'est normal.
                }
                finally
                {
                    connected = false;
                    Release(socket);
                }
                signal.WaitOne(retryMilliseconds);
            }
        }

        // Mémorise la connexion en cours pour que Stop() puisse la fermer. Faux si Stop() est déjà passé.
        bool Register(Socket socket, ManualResetEvent signal)
        {
            lock (gate)
            {
                if (signal.WaitOne(0))
                {
                    return false;
                }
                current = socket;
                return true;
            }
        }

        void Release(Socket socket)
        {
            lock (gate)
            {
                if (current == socket)
                {
                    current = null;
                }
            }
            socket.Close();
        }

        // Lit le socket jusqu'à ce que Python le ferme, qu'une ligne soit trop longue, ou qu'on s'arrête.
        void ReadLines(Socket socket, ManualResetEvent signal)
        {
            var chunk = new byte[ChunkBytes];
            var line = new List<byte>();
            while (!signal.WaitOne(0))
            {
                if (!socket.Poll(PollMicroseconds, SelectMode.SelectRead))
                {
                    continue;
                }
                int count = socket.Receive(chunk);
                if (count == 0)
                {
                    return;
                }
                if (!AppendBytes(chunk, count, line))
                {
                    return;
                }
            }
        }

        // Ajoute les octets reçus à la ligne en cours ; chaque « \n » termine une ligne, qui est publiée.
        // On découpe sur les octets, puis on décode la ligne entière : un caractère UTF-8 (« é » = 2 octets)
        // peut arriver coupé en deux paquets. Faux si une ligne dépasse la taille permise.
        bool AppendBytes(byte[] chunk, int count, List<byte> line)
        {
            for (int index = 0; index < count; index++)
            {
                byte value = chunk[index];
                if (value == NewLine)
                {
                    Publish(line);
                    line.Clear();
                }
                else if (line.Count >= maxLineBytes)
                {
                    return false;
                }
                else
                {
                    line.Add(value);
                }
            }
            return true;
        }

        void Publish(List<byte> line)
        {
            if (line.Count == 0)
            {
                return;
            }
            lines.Enqueue(new ReceivedLine { Connection = connectionCount, Text = Encoding.UTF8.GetString(line.ToArray()) });
        }
    }
}
