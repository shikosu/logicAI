using System;
using System.Collections.Generic;

namespace LogicAI
{
    // Rejoue l'ordre de pose d'une découverte (python/src/logicai/replay.py) : « les nœuds
    // dans l'ordre des signaux, puis les câbles ». Les premières étapes donnent un circuit
    // partiel, que Unity redessine à chaque étape pour montrer la construction pièce par pièce.
    // Unity ne calcule aucune position : x et y sont dans les nœuds, écrits par Python.
    public static class LivePlacement
    {
        public const string PoseAction = "poser";
        public const string WireAction = "cabler";

        // Une broche s'écrit [identifiant du nœud, index].
        const int PinLength = 2;

        // Construit le circuit obtenu après les « count » premières étapes (toutes si count est
        // trop grand). Lève CircuitFormatException si une étape est incohérente : action
        // inconnue, câble posé avant l'un de ses nœuds, broche mal écrite, nœud posé deux fois...
        public static CircuitFile BuildCircuit(string name, PlacementStep[] steps, int count)
        {
            if (steps == null)
            {
                throw new CircuitFormatException("l'ordre de pose manque.");
            }
            if (count < 0)
            {
                throw new CircuitFormatException("le nombre d'étapes " + count + " est négatif.");
            }
            int played = Math.Min(count, steps.Length);
            var nodes = new List<NodeData>();
            var wires = new List<WireData>();
            var posed = new HashSet<int>();
            for (int index = 0; index < played; index++)
            {
                string where = "étape " + index;
                PlacementStep step = steps[index];
                if (step == null)
                {
                    throw new CircuitFormatException(where + " : elle est vide.");
                }
                if (step.action == PoseAction)
                {
                    if (step.noeud == null || string.IsNullOrEmpty(step.noeud.type))
                    {
                        throw new CircuitFormatException(where + " : le nœud manque.");
                    }
                    nodes.Add(step.noeud);
                    posed.Add(step.noeud.id);
                }
                else if (step.action == WireAction)
                {
                    if (step.de == null || step.vers == null
                        || step.de.Length != PinLength || step.vers.Length != PinLength)
                    {
                        throw new CircuitFormatException(where + " : une broche s'écrit [nœud, index].");
                    }
                    if (!posed.Contains(step.de[0]) || !posed.Contains(step.vers[0]))
                    {
                        throw new CircuitFormatException(where + " : le câble touche un nœud pas encore posé.");
                    }
                    wires.Add(new WireData { de = step.de, vers = step.vers });
                }
                else
                {
                    throw new CircuitFormatException(where + " : action inconnue « " + step.action + " ».");
                }
            }
            var file = new CircuitFile { nom = name, noeuds = nodes.ToArray(), cables = wires.ToArray() };
            CircuitLoader.Validate(file);
            return file;
        }
    }
}
