using NUnit.Framework;

namespace LogicAI.Tests
{
    // Tests de la lecture des messages envoyés par Python (voir LiveSamples : les lignes
    // viennent du vrai code Python).
    public class LiveMessageTests
    {
        static LiveMessage Parse(string sample)
        {
            return LiveMessageParser.Parse(LiveSamples.Json(sample));
        }

        // Vérifie qu'un message est refusé, avec une partie attendue dans le texte de l'erreur.
        static void AssertRefused(string sample, string expectedPart)
        {
            var exception = Assert.Throws<LiveMessageException>(() => Parse(sample));
            StringAssert.Contains(expectedPart, exception.Message);
        }

        // --- Lecture de messages valides --------------------------------------------

        [Test]
        public void Parse_CircuitLine_ReadsTheCircuit()
        {
            // Règle vérifiée : message « circuit » = le circuit complet, au format des fichiers.
            LiveMessage message = Parse(LiveSamples.CircuitLine);

            Assert.AreEqual(LiveMessageKind.Circuit, message.Kind);
            Assert.AreEqual("essai", message.Circuit.nom);
            Assert.AreEqual(3, message.Circuit.noeuds.Length);
            Assert.AreEqual(3, message.Circuit.cables.Length);
            Assert.AreEqual("NAND", message.Circuit.noeuds[1].type);
            Assert.AreEqual(2, message.Circuit.noeuds[1].x);
            Assert.IsFalse(CircuitLoader.HasState(message.Circuit));
        }

        [Test]
        public void Parse_StateLine_ReadsTheValues()
        {
            // Règle vérifiée : message « etat » = les valeurs 0/1 de chaque nœud et câble à un top.
            LiveMessage message = Parse(LiveSamples.StateLine);

            Assert.AreEqual(LiveMessageKind.State, message.Kind);
            Assert.AreEqual(1, message.State.top);
            Assert.IsTrue(message.State.stable);
            CollectionAssert.AreEqual(new[] { 0, 1, 1 }, message.State.noeuds);
            CollectionAssert.AreEqual(new[] { 0, 0, 1 }, message.State.cables);
        }

        [Test]
        public void Parse_NotDiscovery_ReadsNameGenreCostCircuitAndSteps()
        {
            // Règle vérifiée : message « decouverte » = nouveau composant + son ordre de pose.
            LiveMessage message = Parse(LiveSamples.NotDiscoveryLine);

            Assert.AreEqual(LiveMessageKind.Discovery, message.Kind);
            DiscoveryData discovery = message.Discovery;
            Assert.AreEqual("NOT", discovery.nom);
            Assert.AreEqual(LiveMessageParser.NewGenre, discovery.genre);
            Assert.AreEqual(1, discovery.cout);
            Assert.AreEqual(3, discovery.circuit.noeuds.Length);
            Assert.AreEqual(6, discovery.ordre_de_pose.Length);
            Assert.AreEqual(LivePlacement.PoseAction, discovery.ordre_de_pose[0].action);
            Assert.AreEqual("ENTREE", discovery.ordre_de_pose[0].noeud.type);
            Assert.AreEqual(LivePlacement.WireAction, discovery.ordre_de_pose[3].action);
            CollectionAssert.AreEqual(new[] { 0, 0 }, discovery.ordre_de_pose[3].de);
            CollectionAssert.AreEqual(new[] { 1, 0 }, discovery.ordre_de_pose[3].vers);
        }

        [Test]
        public void Parse_XorRecord_ReadsTheGenreAndAllSteps()
        {
            // Règle vérifiée : un record est annoncé avec le genre « record » et son coût aplati.
            LiveMessage message = Parse(LiveSamples.XorDiscoveryLine);

            Assert.AreEqual(LiveMessageParser.RecordGenre, message.Discovery.genre);
            Assert.AreEqual(4, message.Discovery.cout);
            Assert.AreEqual(7, message.Discovery.circuit.noeuds.Length);
            Assert.AreEqual(9, message.Discovery.circuit.cables.Length);
            Assert.AreEqual(16, message.Discovery.ordre_de_pose.Length);
        }

        [Test]
        public void Parse_StatsLine_ReadsTheNumbers()
        {
            // Règle vérifiée : message « stats » = palier, génération, découvertes, récompense moyenne.
            LiveMessage message = Parse(LiveSamples.StatsLine);

            Assert.AreEqual(LiveMessageKind.Stats, message.Kind);
            Assert.AreEqual(2, message.Stats.palier);
            Assert.AreEqual(40, message.Stats.generation);
            Assert.AreEqual(5, message.Stats.decouvertes);
            Assert.AreEqual(1.98f, message.Stats.recompense_moyenne, 0.0001f);
        }

        [Test]
        public void Parse_StatsWithAnIntegerReward_IsAccepted()
        {
            // Règle vérifiée : un nombre écrit sans virgule reste un nombre valide.
            LiveMessage message = Parse("{'message':'stats','palier':1,'generation':1,'decouvertes':1,'recompense_moyenne':3}");

            Assert.AreEqual(3f, message.Stats.recompense_moyenne, 0.0001f);
        }

        [Test]
        public void Parse_UnknownExtraKeys_AreIgnored()
        {
            // Règle vérifiée : un champ que cette version ne connaît pas n'empêche pas de lire
            // le message (Python peut évoluer avant Unity).
            LiveMessage message = Parse("{'message':'stats','futur':123,'palier':3,'generation':7,'decouvertes':2,'recompense_moyenne':0.5}");

            Assert.AreEqual(3, message.Stats.palier);
        }

        // --- Messages refusés (Unity ne plante jamais à cause d'une ligne) ----------

        [Test]
        public void Parse_EmptyOrBlank_IsRefused()
        {
            AssertRefused("", "vide");
            AssertRefused("   ", "vide");
        }

        [Test]
        public void Parse_NotJson_IsRefused()
        {
            Assert.Throws<LiveMessageException>(() => LiveMessageParser.Parse("ce n'est pas du JSON"));
        }

        [Test]
        public void Parse_WithoutType_IsRefused()
        {
            AssertRefused("{}", "inconnu");
        }

        [Test]
        public void Parse_UnknownType_IsRefused()
        {
            // Le type « action » du cahier ne sert qu'à la phase 7 : il est inconnu ici.
            AssertRefused("{'message':'action'}", "inconnu");
        }

        [Test]
        public void Parse_CircuitWithAWireToAnUnknownNode_IsRefused()
        {
            // Le circuit d'un message est vérifié comme un fichier de circuit.
            string broken = LiveSamples.CircuitLine.Replace("'vers':[2,0]", "'vers':[9,0]");

            AssertRefused(broken, "n'existe pas");
        }

        [Test]
        public void Parse_CircuitWithoutName_IsRefused()
        {
            AssertRefused("{'message':'circuit','circuit':{'noeuds':[],'cables':[]}}", "nom");
        }

        [Test]
        public void Parse_ErrorMessageNamesTheMessageType()
        {
            string broken = LiveSamples.CircuitLine.Replace("'vers':[2,0]", "'vers':[9,0]");

            AssertRefused(broken, "circuit");
        }

        [Test]
        public void Parse_DiscoveryWithAnUnknownGenre_IsRefused()
        {
            AssertRefused(LiveSamples.NotDiscoveryLine.Replace("'nouveaute'", "'miracle'"), "genre");
        }

        [Test]
        public void Parse_DiscoveryWithANegativeCost_IsRefused()
        {
            AssertRefused(LiveSamples.NotDiscoveryLine.Replace("'cout':1", "'cout':-1"), "coût");
        }

        [Test]
        public void Parse_DiscoveryWithoutName_IsRefused()
        {
            AssertRefused(LiveSamples.NotDiscoveryLine.Replace("'nom':'NOT','genre'", "'genre'"), "nom");
        }

        [Test]
        public void Parse_DiscoveryWithoutCircuit_IsRefused()
        {
            string withoutCircuit = "{'message':'decouverte','nom':'NOT','genre':'nouveaute','cout':1,'ordre_de_pose':[]}";

            Assert.Throws<LiveMessageException>(() => Parse(withoutCircuit));
        }

        [Test]
        public void Parse_DiscoveryWithoutSteps_IsRefused()
        {
            // Sans ordre de pose (clé absente ou liste vide), la rediffusion ne montrerait rien.
            string withoutSteps = "{'message':'decouverte','nom':'VIDE','genre':'nouveaute','cout':0,"
                + "'circuit':{'nom':'VIDE','noeuds':[{'id':0,'type':'ENTREE','x':0,'y':0}],'cables':[]}}";

            Assert.Throws<LiveMessageException>(() => Parse(withoutSteps));
        }

        [Test]
        public void Parse_DiscoveryWhoseStepsDoNotRebuildTheCircuit_IsRefused()
        {
            // On retire la dernière étape de pose (le dernier câble) : l'ordre de pose ne
            // redonne plus le circuit du message.
            string missingStep = LiveSamples.NotDiscoveryLine.Replace(",{'action':'cabler','de':[1,0],'vers':[2,0]}", "");

            AssertRefused(missingStep, "ne redonne pas");
        }

        [Test]
        public void Parse_DiscoveryWithAWireBeforeItsNode_IsRefused()
        {
            // On retire la pose de la NAND : le 1er câble touche un nœud pas encore posé.
            string noNand = LiveSamples.NotDiscoveryLine.Replace("{'action':'poser','noeud':{'id':1,'type':'NAND','x':2,'y':0}},", "");

            AssertRefused(noNand, "pas encore posé");
        }

        [Test]
        public void Parse_DiscoveryWithAnUnknownAction_IsRefused()
        {
            AssertRefused(LiveSamples.NotDiscoveryLine.Replace("'action':'poser'", "'action':'jeter'"), "action inconnue");
        }
    }
}
