using NUnit.Framework;
using UnityEngine;

namespace LogicAI.Tests
{
    // Tests de la géométrie : tailles, broches, tracé des câbles.
    public class CircuitGeometryTests
    {
        static NodeData Node(string type, int x = 0, int y = 0, int inputs = 0, int outputs = 0)
        {
            return new NodeData { id = 0, type = type, x = x, y = y, @ref = type == "COMPOSANT" ? "X" : null, entrees = inputs, sorties = outputs };
        }

        // --- Tailles et nombres de broches ------------------------------------------

        [TestCase("ENTREE", 0, 1)]
        [TestCase("SORTIE", 1, 0)]
        [TestCase("NAND", 2, 1)]
        public void PinCounts_OfFixedKinds_FollowTheSpecification(string type, int sinks, int sources)
        {
            // Règle vérifiée : prompt phase 1, section A (puits et sources de chaque type).
            NodeData node = Node(type);
            Assert.AreEqual(sinks, CircuitGeometry.SinkCount(node));
            Assert.AreEqual(sources, CircuitGeometry.SourceCount(node));
        }

        [TestCase("NAND", 0, 0, 2)]
        [TestCase("ENTREE", 0, 0, 2)]
        [TestCase("COMPOSANT", 0, 0, 2)]
        [TestCase("COMPOSANT", 3, 1, 4)]
        [TestCase("COMPOSANT", 1, 5, 6)]
        [TestCase("COMPOSANT", 4, 4, 4)]
        public void BoxHeight_IsThePinCountRoundedUpToAnEvenNumber(string type, int inputs, int outputs, int expected)
        {
            // Règle vérifiée : même règle que Python (layout.box_height) : max(2, broches),
            // arrondi au pair. Mêmes valeurs que test_box_height_... côté Python.
            Assert.AreEqual(expected, CircuitGeometry.BoxHeight(Node(type, 0, 0, inputs, outputs)));
        }

        [Test]
        public void CenterAndSize_ScaleTheFileUnits()
        {
            // Règle vérifiée : décision du plan (Python place, Unity convertit en unités).
            NodeData node = Node("NAND", 2, 2);
            Assert.AreEqual(new Vector2(2f * CircuitGeometry.XScale, 2f * CircuitGeometry.YScale), CircuitGeometry.Center(node));
            Assert.AreEqual(new Vector2(CircuitGeometry.BoxWidth, 2f * CircuitGeometry.YScale), CircuitGeometry.Size(node));
        }

        // --- Broches ----------------------------------------------------------------

        [Test]
        public void NandPins_AreOnTheLeftAndRightEdges()
        {
            // Règle vérifiée : décision du plan (puits à gauche, source à droite ; la
            // première broche en haut).
            NodeData nand = Node("NAND", 2, 0);
            Vector2 center = CircuitGeometry.Center(nand);
            float half = CircuitGeometry.BoxWidth / 2f;
            float step = CircuitGeometry.YScale;

            Assert.AreEqual(new Vector2(center.x - half, +step / 2f), CircuitGeometry.SinkPin(nand, 0));
            Assert.AreEqual(new Vector2(center.x - half, -step / 2f), CircuitGeometry.SinkPin(nand, 1));
            Assert.AreEqual(new Vector2(center.x + half, 0f), CircuitGeometry.SourcePin(nand, 0));
        }

        [Test]
        public void ComponentPins_AreSpreadAroundTheCenter()
        {
            // Règle vérifiée : cahier, « Les éléments » (un composant a n puits et m sources).
            NodeData component = Node("COMPOSANT", 0, 0, 3, 2);
            float step = CircuitGeometry.YScale;

            Assert.AreEqual(+step, CircuitGeometry.SinkPin(component, 0).y, 1e-5f);
            Assert.AreEqual(0f, CircuitGeometry.SinkPin(component, 1).y, 1e-5f);
            Assert.AreEqual(-step, CircuitGeometry.SinkPin(component, 2).y, 1e-5f);
            Assert.AreEqual(+step / 2f, CircuitGeometry.SourcePin(component, 0).y, 1e-5f);
            Assert.AreEqual(-step / 2f, CircuitGeometry.SourcePin(component, 1).y, 1e-5f);
        }

        [Test]
        public void AllPinsStayInsideTheirBox()
        {
            // Règle vérifiée : décision du plan (la boîte fait max(2, broches) unités : une
            // unité entre deux broches, donc toutes les broches tiennent dans la boîte).
            for (int inputs = 0; inputs <= 9; inputs++)
            {
                NodeData component = Node("COMPOSANT", 3, -2, inputs, 9 - inputs);
                Vector2 center = CircuitGeometry.Center(component);
                float halfHeight = CircuitGeometry.Size(component).y / 2f;
                for (int pin = 0; pin < inputs; pin++)
                {
                    Assert.LessOrEqual(Mathf.Abs(CircuitGeometry.SinkPin(component, pin).y - center.y), halfHeight);
                }
                for (int pin = 0; pin < 9 - inputs; pin++)
                {
                    Assert.LessOrEqual(Mathf.Abs(CircuitGeometry.SourcePin(component, pin).y - center.y), halfHeight);
                }
            }
        }

        // --- Tracé des câbles --------------------------------------------------------

        static void AssertOrthogonal(Vector2[] route)
        {
            for (int i = 1; i < route.Length; i++)
            {
                bool horizontal = Mathf.Approximately(route[i].y, route[i - 1].y);
                bool vertical = Mathf.Approximately(route[i].x, route[i - 1].x);
                Assert.IsTrue(horizontal || vertical, "segment non horizontal ni vertical entre " + route[i - 1] + " et " + route[i]);
            }
        }

        [Test]
        public void Route_ForwardOnTheSameHeight_IsAStraightLine()
        {
            Vector2[] route = CircuitGeometry.Route(new Vector2(1f, 0f), new Vector2(3f, 0f));
            Assert.AreEqual(2, route.Length);
        }

        [Test]
        public void Route_ForwardWithAHeightDifference_HasAVerticalStepInTheMiddle()
        {
            Vector2[] route = CircuitGeometry.Route(new Vector2(1f, 0f), new Vector2(3f, 1f));

            Assert.AreEqual(4, route.Length);
            Assert.AreEqual(new Vector2(1f, 0f), route[0]);
            Assert.AreEqual(new Vector2(3f, 1f), route[3]);
            Assert.AreEqual(2f, route[1].x, 1e-5f);
            AssertOrthogonal(route);
        }

        [Test]
        public void Route_Backward_GoesAroundAboveBothPins()
        {
            // Règle vérifiée : cahier, règle de câblage n°5 (les boucles sont autorisées) :
            // un câble qui revient en arrière passe au-dessus des deux broches.
            Vector2 start = new Vector2(3f, 0f);
            Vector2 end = new Vector2(1f, 0.5f);

            Vector2[] route = CircuitGeometry.Route(start, end);

            Assert.AreEqual(6, route.Length);
            Assert.AreEqual(start, route[0]);
            Assert.AreEqual(end, route[5]);
            Assert.Greater(route[2].y, Mathf.Max(start.y, end.y));
            AssertOrthogonal(route);
        }

        [Test]
        public void Route_OfAGateLoopedOnItself_StartsAtItsSourceAndEndsAtItsSink()
        {
            // Règle vérifiée : cahier, règle de câblage n°5 (une sortie qui revient sur sa
            // propre porte) : le NOT rebouclé.
            NodeData nand = Node("NAND", 2, 0);
            Vector2 source = CircuitGeometry.SourcePin(nand, 0);
            Vector2 sink = CircuitGeometry.SinkPin(nand, 1);

            Vector2[] route = CircuitGeometry.Route(source, sink);

            Assert.AreEqual(source, route[0]);
            Assert.AreEqual(sink, route[route.Length - 1]);
            float boxTop = CircuitGeometry.Center(nand).y + CircuitGeometry.Size(nand).y / 2f;
            Assert.Greater(route[2].y, boxTop);
            AssertOrthogonal(route);
        }

        [Test]
        public void Route_AlwaysStartsAndEndsAtThePinsAndIsOrthogonal()
        {
            // Règle vérifiée : décision du plan (tracé en segments horizontaux et verticaux),
            // sur une grille de positions de départ et d'arrivée, vers l'avant et en arrière.
            for (float sx = -3f; sx <= 3f; sx += 1.5f)
            {
                for (float tx = -3f; tx <= 3f; tx += 1.5f)
                {
                    for (float sy = -1f; sy <= 1f; sy += 0.5f)
                    {
                        for (float ty = -1f; ty <= 1f; ty += 0.5f)
                        {
                            var start = new Vector2(sx, sy);
                            var end = new Vector2(tx, ty);
                            Vector2[] route = CircuitGeometry.Route(start, end);
                            Assert.AreEqual(start, route[0]);
                            Assert.AreEqual(end, route[route.Length - 1]);
                            AssertOrthogonal(route);
                        }
                    }
                }
            }
        }

        // --- Cadrage -----------------------------------------------------------------

        [Test]
        public void Bounds_ContainEveryBoxWithTheMargin()
        {
            // Règle vérifiée : décision du plan (la caméra est cadrée sur le circuit).
            var file = new CircuitFile
            {
                nom = "X",
                noeuds = new[] { Node("ENTREE", 0, 0), Node("NAND", 2, 2), Node("SORTIE", 4, -2) },
            };

            Rect bounds = CircuitGeometry.Bounds(file, 1f);

            foreach (NodeData node in file.noeuds)
            {
                Vector2 center = CircuitGeometry.Center(node);
                Vector2 half = CircuitGeometry.Size(node) / 2f;
                Assert.LessOrEqual(bounds.xMin, center.x - half.x - 1f + 1e-4f);
                Assert.GreaterOrEqual(bounds.xMax, center.x + half.x + 1f - 1e-4f);
                Assert.LessOrEqual(bounds.yMin, center.y - half.y - 1f + 1e-4f);
                Assert.GreaterOrEqual(bounds.yMax, center.y + half.y + 1f - 1e-4f);
            }
        }

        [Test]
        public void Bounds_OfAnEmptyCircuit_AreASmallRectangleAroundTheOrigin()
        {
            Rect bounds = CircuitGeometry.Bounds(new CircuitFile { nom = "VIDE", noeuds = new NodeData[0] }, 1f);
            Assert.Greater(bounds.width, 0f);
            Assert.Greater(bounds.height, 0f);
            Assert.IsTrue(bounds.Contains(Vector2.zero));
        }
    }
}
