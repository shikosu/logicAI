namespace LogicAI.Tests
{
    // Des lignes de messages écrites par le vrai code Python (protocol.py), avec « ' » à la place de
    // « " » pour les écrire dans du C# (la méthode Json les remet). Fichier généré : ne pas modifier
    // à la main ; en cas de changement du protocole, le régénérer depuis Python.
    public static class LiveSamples
    {
        // Pour écrire du JSON dans du C# sans doubler les guillemets : ' devient ".
        public static string Json(string text)
        {
            return text.Replace('\'', '"');
        }

        // Message « circuit » : le circuit d'un essai montré (un NOT).
        public const string CircuitLine =
            "{'message':'circuit','circuit':{'nom':'essai','noeuds':[{'id':0,'type':'ENTREE','x':0,'y':0},{'id':1,'type':'NAND','x':2,'y':0},{'id':2,'type':'SORTIE','x':4,'y':0}],'cables':[{'de':[0,0],'vers':[1,0]},{'de':[0,0],'vers':[1,1]},{'de':[1,0],'vers':[2,0]}]}}";

        // Message « etat » : les valeurs du NOT avec A = 0 au top 1 (stable).
        public const string StateLine =
            "{'message':'etat','etat':{'top':1,'stable':true,'noeuds':[0,1,1],'cables':[0,0,1]}}";

        // Message « decouverte » : le NOT, une nouveauté de 1 NAND.
        public const string NotDiscoveryLine =
            "{'message':'decouverte','nom':'NOT','genre':'nouveaute','cout':1,'circuit':{'nom':'NOT','noeuds':[{'id':0,'type':'ENTREE','x':0,'y':0},{'id':1,'type':'NAND','x':2,'y':0},{'id':2,'type':'SORTIE','x':4,'y':0}],'cables':[{'de':[0,0],'vers':[1,0]},{'de':[0,0],'vers':[1,1]},{'de':[1,0],'vers':[2,0]}]},'ordre_de_pose':[{'action':'poser','noeud':{'id':0,'type':'ENTREE','x':0,'y':0}},{'action':'poser','noeud':{'id':1,'type':'NAND','x':2,'y':0}},{'action':'poser','noeud':{'id':2,'type':'SORTIE','x':4,'y':0}},{'action':'cabler','de':[0,0],'vers':[1,0]},{'action':'cabler','de':[0,0],'vers':[1,1]},{'action':'cabler','de':[1,0],'vers':[2,0]}]}";

        // Message « decouverte » : le XOR, un record de 4 NAND (7 nœuds, 9 câbles, 16 étapes).
        public const string XorDiscoveryLine =
            "{'message':'decouverte','nom':'XOR','genre':'record','cout':4,'circuit':{'nom':'XOR','noeuds':[{'id':0,'type':'ENTREE','x':0,'y':2},{'id':1,'type':'ENTREE','x':0,'y':-2},{'id':2,'type':'NAND','x':2,'y':0},{'id':3,'type':'NAND','x':4,'y':2},{'id':4,'type':'NAND','x':4,'y':-2},{'id':5,'type':'NAND','x':6,'y':0},{'id':6,'type':'SORTIE','x':8,'y':0}],'cables':[{'de':[0,0],'vers':[2,0]},{'de':[1,0],'vers':[2,1]},{'de':[0,0],'vers':[3,0]},{'de':[2,0],'vers':[3,1]},{'de':[1,0],'vers':[4,0]},{'de':[2,0],'vers':[4,1]},{'de':[3,0],'vers':[5,0]},{'de':[4,0],'vers':[5,1]},{'de':[5,0],'vers':[6,0]}]},'ordre_de_pose':[{'action':'poser','noeud':{'id':1,'type':'ENTREE','x':0,'y':-2}},{'action':'poser','noeud':{'id':0,'type':'ENTREE','x':0,'y':2}},{'action':'poser','noeud':{'id':2,'type':'NAND','x':2,'y':0}},{'action':'poser','noeud':{'id':4,'type':'NAND','x':4,'y':-2}},{'action':'poser','noeud':{'id':3,'type':'NAND','x':4,'y':2}},{'action':'poser','noeud':{'id':5,'type':'NAND','x':6,'y':0}},{'action':'poser','noeud':{'id':6,'type':'SORTIE','x':8,'y':0}},{'action':'cabler','de':[0,0],'vers':[2,0]},{'action':'cabler','de':[1,0],'vers':[2,1]},{'action':'cabler','de':[1,0],'vers':[4,0]},{'action':'cabler','de':[2,0],'vers':[4,1]},{'action':'cabler','de':[0,0],'vers':[3,0]},{'action':'cabler','de':[2,0],'vers':[3,1]},{'action':'cabler','de':[3,0],'vers':[5,0]},{'action':'cabler','de':[4,0],'vers':[5,1]},{'action':'cabler','de':[5,0],'vers':[6,0]}]}";

        // Message « stats » : palier 2, génération 40, 5 découvertes, récompense moyenne 1,98.
        public const string StatsLine =
            "{'message':'stats','palier':2,'generation':40,'decouvertes':5,'recompense_moyenne':1.98}";
    }
}
