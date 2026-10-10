using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace LogicAI
{
    // Une erreur dans un fichier de circuit : le message dit ce qui est refusé et pourquoi.
    public class CircuitFormatException : Exception
    {
        public CircuitFormatException(string message) : base(message) { }
    }

    // Lit un fichier de circuit et vérifie qu'il est cohérent. Unity ne calcule rien :
    // il refuse seulement un fichier qu'il ne saurait pas dessiner.
    public static class CircuitLoader
    {
        // Les types écrits par Python (serialization.py) et leur sens.
        static readonly Dictionary<string, NodeKind> KindOfType = new Dictionary<string, NodeKind>
        {
            { "ENTREE", NodeKind.Input },
            { "SORTIE", NodeKind.Output },
            { "NAND", NodeKind.Nand },
            { "COMPOSANT", NodeKind.Component },
        };

        // Une broche s'écrit [identifiant du nœud, index].
        const int PinLength = 2;

        public static CircuitFile Load(string path)
        {
            string json;
            try
            {
                json = File.ReadAllText(path);
            }
            catch (IOException exception)
            {
                throw new CircuitFormatException(Path.GetFileName(path) + " : fichier illisible (" + exception.Message + ").");
            }
            try
            {
                return Parse(json);
            }
            catch (CircuitFormatException exception)
            {
                throw new CircuitFormatException(Path.GetFileName(path) + " : " + exception.Message);
            }
        }

        public static CircuitFile Parse(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                throw new CircuitFormatException("le fichier est vide.");
            }
            CircuitFile file;
            try
            {
                file = JsonUtility.FromJson<CircuitFile>(json);
            }
            catch (ArgumentException exception)
            {
                throw new CircuitFormatException("ce n'est pas du JSON valide (" + exception.Message + ").");
            }
            Validate(file);
            return file;
        }

        // Le type d'un nœud. Appelée après Validate, donc le texte est connu.
        public static NodeKind KindOf(NodeData node)
        {
            return KindOfType[node.type];
        }

        // Dit si le fichier contient les valeurs 0/1 d'un top (la clé « etat »).
        public static bool HasState(CircuitFile file)
        {
            return file.etat != null
                && file.etat.noeuds != null
                && file.etat.cables != null;
        }

        // Vérifie qu'un circuit est cohérent (nœuds, câbles, broches, valeurs). Publique : les
        // messages reçus de Python (LiveMessageParser) contiennent aussi des circuits.
        public static void Validate(CircuitFile file)
        {
            if (file == null || string.IsNullOrEmpty(file.nom))
            {
                throw new CircuitFormatException("la clé « nom » manque.");
            }
            NodeData[] nodes = file.noeuds ?? new NodeData[0];
            WireData[] wires = file.cables ?? new WireData[0];

            var nodesById = new Dictionary<int, NodeData>();
            foreach (NodeData node in nodes)
            {
                ValidateNode(node, nodesById);
                nodesById.Add(node.id, node);
            }
            for (int index = 0; index < wires.Length; index++)
            {
                ValidateWire(wires[index], index, nodesById);
            }
            if (HasState(file))
            {
                ValidateState(file.etat, nodes.Length, wires.Length);
            }
        }

        static void ValidateNode(NodeData node, Dictionary<int, NodeData> nodesById)
        {
            if (node == null || string.IsNullOrEmpty(node.type))
            {
                throw new CircuitFormatException("un nœud n'a pas de type.");
            }
            if (!KindOfType.ContainsKey(node.type))
            {
                throw new CircuitFormatException("le nœud " + node.id + " a un type inconnu : « " + node.type + " ».");
            }
            if (nodesById.ContainsKey(node.id))
            {
                throw new CircuitFormatException("l'identifiant " + node.id + " est utilisé deux fois.");
            }
            if (KindOfType[node.type] == NodeKind.Component)
            {
                if (string.IsNullOrEmpty(node.@ref))
                {
                    throw new CircuitFormatException("le composant " + node.id + " n'a pas de nom (« ref »).");
                }
                if (node.entrees < 0 || node.sorties < 0)
                {
                    throw new CircuitFormatException("le composant " + node.id + " a un nombre de broches négatif.");
                }
            }
        }

        static void ValidateWire(WireData wire, int index, Dictionary<int, NodeData> nodesById)
        {
            string where = "câble " + index;
            if (wire == null || wire.de == null || wire.vers == null
                || wire.de.Length != PinLength || wire.vers.Length != PinLength)
            {
                throw new CircuitFormatException(where + " : une broche s'écrit [nœud, index].");
            }
            CheckPin(wire.de, CircuitGeometry.SourceCount, "de", where, nodesById);
            CheckPin(wire.vers, CircuitGeometry.SinkCount, "vers", where, nodesById);
        }

        static void CheckPin(int[] pin, Func<NodeData, int> pinCount, string label, string where, Dictionary<int, NodeData> nodesById)
        {
            NodeData node;
            if (!nodesById.TryGetValue(pin[0], out node))
            {
                throw new CircuitFormatException(where + " : le nœud " + pin[0] + " (« " + label + " ») n'existe pas.");
            }
            if (pin[1] < 0 || pin[1] >= pinCount(node))
            {
                throw new CircuitFormatException(where + " : le nœud " + pin[0] + " n'a pas de broche " + pin[1] + " de ce genre (« " + label + " »).");
            }
        }

        static void ValidateState(StateData state, int nodeCount, int wireCount)
        {
            if (state.noeuds.Length != nodeCount || state.cables.Length != wireCount)
            {
                throw new CircuitFormatException(
                    "« etat » a " + state.noeuds.Length + " valeurs de nœuds et " + state.cables.Length
                    + " de câbles, mais le circuit a " + nodeCount + " nœuds et " + wireCount + " câbles.");
            }
        }
    }
}
