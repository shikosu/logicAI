using System;
using UnityEngine;

namespace LogicAI
{
    // Les messages que Python envoie à Unity par le socket (voir python/src/logicai/protocol.py).
    // Chaque message est une ligne de JSON, avec une clé « message » qui donne son type :
    //   circuit     { "message": "circuit", "circuit": <fichier de circuit> }
    //   etat        { "message": "etat", "etat": { top, stable, noeuds, cables } }
    //   decouverte  { "message": "decouverte", nom, genre, cout, circuit, ordre_de_pose }
    //   stats       { "message": "stats", palier, generation, decouvertes, recompense_moyenne }
    //
    // Comme pour les fichiers de circuit, les champs ont les noms des clés du JSON (en
    // français) : JsonUtility, l'outil de Unity qui lit le JSON, l'exige.

    public enum LiveMessageKind
    {
        Circuit,
        State,
        Discovery,
        Stats,
    }

    // Une étape de l'ordre de pose d'une découverte : « poser » un nœud (champ noeud) ou
    // « cabler » deux broches (champs de et vers).
    [Serializable]
    public class PlacementStep
    {
        public string action;
        public NodeData noeud;
        public int[] de;
        public int[] vers;
    }

    // Une découverte : un nouveau composant (genre « nouveaute ») ou une version plus petite
    // d'un composant connu (genre « record »), avec son circuit et son ordre de pose.
    [Serializable]
    public class DiscoveryData
    {
        public string nom;
        public string genre;
        public int cout;
        public CircuitFile circuit;
        public PlacementStep[] ordre_de_pose;
    }

    // Les statistiques du panneau d'information.
    [Serializable]
    public class StatsData
    {
        public int palier;
        public int generation;
        public int decouvertes;
        public float recompense_moyenne;
    }

    // Les « enveloppes » dont JsonUtility a besoin pour lire une seule clé d'un message.
    [Serializable]
    public class MessageHeader
    {
        public string message;
    }

    [Serializable]
    public class CircuitEnvelope
    {
        public CircuitFile circuit;
    }

    [Serializable]
    public class StateEnvelope
    {
        public StateData etat;
    }

    // Un message lu et vérifié. Seul le champ qui correspond à Kind est rempli.
    public class LiveMessage
    {
        public LiveMessageKind Kind;
        public CircuitFile Circuit;
        public StateData State;
        public DiscoveryData Discovery;
        public StatsData Stats;
    }

    // Un message reçu qu'on ne sait pas lire : le texte dit ce qui est refusé et pourquoi.
    public class LiveMessageException : Exception
    {
        public LiveMessageException(string message) : base(message) { }
    }

    // Lit une ligne reçue de Python. Parse renvoie un message vérifié, ou lève
    // LiveMessageException : Unity ne plante jamais à cause d'une ligne incorrecte.
    public static class LiveMessageParser
    {
        public const string CircuitType = "circuit";
        public const string StateType = "etat";
        public const string DiscoveryType = "decouverte";
        public const string StatsType = "stats";

        public const string NewGenre = "nouveaute";
        public const string RecordGenre = "record";

        public static LiveMessage Parse(string line)
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                throw new LiveMessageException("le message est vide.");
            }
            MessageHeader header = FromJson<MessageHeader>(line);
            string type = header == null ? null : header.message;
            try
            {
                switch (type)
                {
                    case CircuitType:
                        return ParseCircuit(line);
                    case StateType:
                        return ParseState(line);
                    case DiscoveryType:
                        return ParseDiscovery(line);
                    case StatsType:
                        return ParseStats(line);
                    default:
                        throw new LiveMessageException("type de message inconnu : « " + type + " ».");
                }
            }
            catch (CircuitFormatException exception)
            {
                throw new LiveMessageException("message « " + type + " » : " + exception.Message);
            }
        }

        static T FromJson<T>(string line)
        {
            try
            {
                return JsonUtility.FromJson<T>(line);
            }
            catch (ArgumentException exception)
            {
                throw new LiveMessageException("ce n'est pas du JSON valide (" + exception.Message + ").");
            }
        }

        static LiveMessage ParseCircuit(string line)
        {
            CircuitEnvelope envelope = FromJson<CircuitEnvelope>(line);
            CircuitFile circuit = envelope == null ? null : envelope.circuit;
            CircuitLoader.Validate(circuit);
            return new LiveMessage { Kind = LiveMessageKind.Circuit, Circuit = circuit };
        }

        static LiveMessage ParseState(string line)
        {
            StateEnvelope envelope = FromJson<StateEnvelope>(line);
            StateData state = envelope == null ? null : envelope.etat;
            if (state == null || state.noeuds == null || state.cables == null)
            {
                throw new LiveMessageException("message « etat » : la clé « etat » manque ou est incomplète.");
            }
            return new LiveMessage { Kind = LiveMessageKind.State, State = state };
        }

        static LiveMessage ParseDiscovery(string line)
        {
            DiscoveryData data = FromJson<DiscoveryData>(line);
            if (data == null || string.IsNullOrEmpty(data.nom))
            {
                throw new LiveMessageException("message « decouverte » : la clé « nom » manque.");
            }
            if (data.genre != NewGenre && data.genre != RecordGenre)
            {
                throw new LiveMessageException("message « decouverte » : le genre « " + data.genre + " » est inconnu.");
            }
            if (data.cout < 0)
            {
                throw new LiveMessageException("message « decouverte » : le coût est négatif.");
            }
            CircuitLoader.Validate(data.circuit);
            if (data.ordre_de_pose == null)
            {
                throw new LiveMessageException("message « decouverte » : la clé « ordre_de_pose » manque.");
            }
            // L'ordre de pose doit redonner le circuit du message (sinon la rediffusion montrerait autre chose).
            CircuitFile rebuilt = LivePlacement.BuildCircuit(data.nom, data.ordre_de_pose, data.ordre_de_pose.Length);
            if (Count(rebuilt.noeuds) != Count(data.circuit.noeuds) || Count(rebuilt.cables) != Count(data.circuit.cables))
            {
                throw new LiveMessageException("message « decouverte » : l'ordre de pose ne redonne pas le circuit.");
            }
            return new LiveMessage { Kind = LiveMessageKind.Discovery, Discovery = data };
        }

        static LiveMessage ParseStats(string line)
        {
            StatsData stats = FromJson<StatsData>(line);
            if (stats == null)
            {
                throw new LiveMessageException("message « stats » : illisible.");
            }
            return new LiveMessage { Kind = LiveMessageKind.Stats, Stats = stats };
        }

        static int Count<T>(T[] items)
        {
            return items == null ? 0 : items.Length;
        }
    }
}
