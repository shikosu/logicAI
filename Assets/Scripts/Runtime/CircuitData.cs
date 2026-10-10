using System;

namespace LogicAI
{
    // Les données d'un fichier de circuit, telles que Python les écrit (voir
    // python/src/logicai/serialization.py).
    //
    // Les noms des champs sont ceux du fichier JSON, donc en français : JsonUtility
    // (l'outil de Unity qui lit le JSON) exige des noms identiques aux clés. Tout le reste
    // du code est en anglais.

    // Un fichier de circuit : son nom, ses nœuds, ses câbles, et facultativement les
    // valeurs 0/1 à un top (« etat »).
    [Serializable]
    public class CircuitFile
    {
        public string nom;
        public NodeData[] noeuds;
        public WireData[] cables;
        public StateData etat;
    }

    // Un nœud : entrée du circuit, sortie du circuit, NAND ou composant.
    // x et y sont calculés par Python. Seul un composant a ref, entrees et sorties.
    [Serializable]
    public class NodeData
    {
        public int id;
        public string type;
        public int x;
        public int y;
        public string @ref;
        public int entrees;
        public int sorties;
    }

    // Un câble : de [nœud, broche source] vers [nœud, broche puits].
    [Serializable]
    public class WireData
    {
        public int[] de;
        public int[] vers;
    }

    // Les valeurs 0/1 du circuit à un top. Les deux listes suivent l'ordre de noeuds et de
    // cables du fichier.
    [Serializable]
    public class StateData
    {
        public int top;
        public bool stable;
        public int[] noeuds;
        public int[] cables;
    }

    // Le type d'un nœud, déduit du texte du fichier (« ENTREE », « SORTIE »...).
    public enum NodeKind
    {
        Input,
        Output,
        Nand,
        Component,
    }
}
