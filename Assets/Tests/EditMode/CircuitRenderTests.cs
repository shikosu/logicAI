using System;
using System.Collections.Generic;
using System.IO;
using NUnit.Framework;
using UnityEngine;

namespace LogicAI.Tests
{
    // Tests du dessin : on dessine un circuit dans une image hors écran, puis on lit les
    // pixels aux endroits où doivent être les câbles et les portes. Si la variable
    // d'environnement LOGICAI_RENDER_DIR est définie, chaque image est aussi écrite en PNG.
    public class CircuitRenderTests
    {
        const int Width = 960;
        const int Height = 540;
        const float CameraMargin = 1.2f;
        static readonly Color ClearColor = new Color(0.02f, 0.02f, 0.03f);

        GameObject cameraObject;
        GameObject drawn;
        Camera camera;
        RenderTexture target;

        [SetUp]
        public void SetUp()
        {
            cameraObject = new GameObject("TestCamera");
            camera = cameraObject.AddComponent<Camera>();
            camera.orthographic = true;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = ClearColor;
            target = new RenderTexture(Width, Height, 24);
            camera.targetTexture = target;
        }

        [TearDown]
        public void TearDown()
        {
            if (drawn != null) UnityEngine.Object.DestroyImmediate(drawn);
            UnityEngine.Object.DestroyImmediate(cameraObject);
            target.Release();
            UnityEngine.Object.DestroyImmediate(target);
        }

        // --- Outils ------------------------------------------------------------------

        static string CircuitsFolder()
        {
            return CircuitViewer.DefaultFolder();
        }

        Texture2D Render(CircuitFile file)
        {
            drawn = CircuitDrawer.Draw(file);
            Vector2 center;
            float size;
            CircuitGeometry.FitCamera(CircuitGeometry.Bounds(file, CameraMargin), Width / (float)Height, out center, out size);
            camera.transform.position = new Vector3(center.x, center.y, -10f);
            camera.orthographicSize = size;
            camera.Render();

            RenderTexture.active = target;
            var image = new Texture2D(Width, Height, TextureFormat.RGBA32, false);
            image.ReadPixels(new Rect(0, 0, Width, Height), 0, 0);
            image.Apply();
            RenderTexture.active = null;

            string directory = Environment.GetEnvironmentVariable("LOGICAI_RENDER_DIR");
            if (!string.IsNullOrEmpty(directory))
            {
                Directory.CreateDirectory(directory);
                File.WriteAllBytes(Path.Combine(directory, file.nom + ".png"), image.EncodeToPNG());
            }
            return image;
        }

        Color PixelAt(Texture2D image, Vector2 world)
        {
            Vector3 screen = camera.WorldToScreenPoint(new Vector3(world.x, world.y, 0f));
            return image.GetPixel(Mathf.RoundToInt(screen.x), Mathf.RoundToInt(screen.y));
        }

        // Les couleurs que l'on s'attend à trouver dans l'image.
        static readonly Dictionary<string, Color> Palette = new Dictionary<string, Color>
        {
            { "zéro", CircuitPalette.Zero },
            { "un", CircuitPalette.One },
            { "inconnu", CircuitPalette.Unknown },
            { "intérieur de porte", CircuitPalette.NodeFill },
            { "fond stable", CircuitPalette.BackdropStable },
            { "fond instable", CircuitPalette.BackdropUnstable },
            { "hors du fond", ClearColor },
        };

        // Le nom de la couleur attendue la plus proche d'un pixel : cela évite de dépendre
        // des petites différences de conversion de couleur du rendu.
        static string NearestName(Color pixel)
        {
            string best = null;
            float bestDistance = float.MaxValue;
            foreach (KeyValuePair<string, Color> entry in Palette)
            {
                Vector3 difference = new Vector3(pixel.r - entry.Value.r, pixel.g - entry.Value.g, pixel.b - entry.Value.b);
                if (difference.sqrMagnitude < bestDistance)
                {
                    bestDistance = difference.sqrMagnitude;
                    best = entry.Key;
                }
            }
            return best;
        }

        static string NameOfValue(int value)
        {
            if (value == 0) return "zéro";
            if (value == 1) return "un";
            return "inconnu";
        }

        static NodeData NodeById(CircuitFile file, int id)
        {
            foreach (NodeData node in file.noeuds)
            {
                if (node.id == id) return node;
            }
            throw new ArgumentException("nœud " + id);
        }

        // Un point au milieu du dernier segment d'un câble (celui qui arrive sur la broche
        // puits) : deux câbles différents n'y passent jamais ensemble.
        static Vector2 LastSegmentMiddle(CircuitFile file, WireData wire)
        {
            Vector2[] route = CircuitGeometry.Route(
                CircuitGeometry.SourcePin(NodeById(file, wire.de[0]), wire.de[1]),
                CircuitGeometry.SinkPin(NodeById(file, wire.vers[0]), wire.vers[1]),
                wire.vers[1]);
            return (route[route.Length - 1] + route[route.Length - 2]) / 2f;
        }

        // --- Les câbles --------------------------------------------------------------

        [Test]
        public void Render_NotWithA0_ColorsEachWireByItsValue()
        {
            // Règle vérifiée : cahier, plan de développement, phase 3 (câbles colorés selon
            // leur valeur). NOT avec A = 0 : les deux câbles d'entrée valent 0, la sortie 1.
            CircuitFile file = CircuitLoader.Load(Path.Combine(CircuitsFolder(), "not_A0.json"));
            Texture2D image = Render(file);

            Assert.AreEqual("zéro", NearestName(PixelAt(image, LastSegmentMiddle(file, file.cables[0]))));
            Assert.AreEqual("zéro", NearestName(PixelAt(image, LastSegmentMiddle(file, file.cables[1]))));
            Assert.AreEqual("un", NearestName(PixelAt(image, LastSegmentMiddle(file, file.cables[2]))));
        }

        [Test]
        public void Render_EveryWireOfEveryPythonFile_HasTheColorOfItsValue()
        {
            // Règle vérifiée : cahier, plan de développement, phase 3 (les circuits de la
            // phase 1 s'affichent correctement, câbles colorés selon leur valeur) : les 31
            // fichiers écrits par Python, chaque câble, lu au pixel.
            string[] paths = Directory.GetFiles(CircuitsFolder(), "*.json");
            Assert.AreEqual(31, paths.Length);
            Array.Sort(paths, StringComparer.Ordinal);

            foreach (string path in paths)
            {
                CircuitFile file = CircuitLoader.Load(path);
                Texture2D image = Render(file);
                for (int i = 0; i < file.cables.Length; i++)
                {
                    Color pixel = PixelAt(image, LastSegmentMiddle(file, file.cables[i]));
                    Assert.AreEqual(NameOfValue(file.etat.cables[i]), NearestName(pixel), file.nom + ", câble " + i + " (pixel " + pixel + ")");
                }
                UnityEngine.Object.DestroyImmediate(drawn);
                drawn = null;
            }
        }

        [Test]
        public void Render_WithoutState_ColorsWiresWithTheNeutralColor()
        {
            // Règle vérifiée : décision du plan (un fichier sans « etat » : câbles gris clair).
            CircuitFile file = CircuitLoader.Load(Path.Combine(CircuitsFolder(), "not_A0.json"));
            file.etat = null;
            Texture2D image = Render(file);

            foreach (WireData wire in file.cables)
            {
                Assert.AreEqual("inconnu", NearestName(PixelAt(image, LastSegmentMiddle(file, wire))));
            }
        }

        // --- Les portes --------------------------------------------------------------

        [Test]
        public void Render_InputsAndOutputs_AreFilledWithTheirValue()
        {
            // Règle vérifiée : cahier, message « etat » : XOR avec A = 1, B = 0 : A est jaune,
            // B est bleu-gris, la sortie vaut 1. On lit un coin de la boîte, loin du texte.
            CircuitFile file = CircuitLoader.Load(Path.Combine(CircuitsFolder(), "xor_A1_B0.json"));
            Texture2D image = Render(file);

            for (int i = 0; i < file.noeuds.Length; i++)
            {
                NodeKind kind = CircuitLoader.KindOf(file.noeuds[i]);
                if (kind != NodeKind.Input && kind != NodeKind.Output) continue;
                Vector2 corner = CircuitGeometry.Center(file.noeuds[i]) + new Vector2(-0.3f, 0.3f);
                Assert.AreEqual(NameOfValue(file.etat.noeuds[i]), NearestName(PixelAt(image, corner)), "nœud " + file.noeuds[i].id);
            }
        }

        [Test]
        public void Render_GatesHaveADarkBodyAndABorderOfTheirValue()
        {
            // Règle vérifiée : décision du plan (une porte a un intérieur sombre et un bord
            // de la couleur de sa valeur).
            CircuitFile file = CircuitLoader.Load(Path.Combine(CircuitsFolder(), "xor_A1_B0.json"));
            Texture2D image = Render(file);

            int gates = 0;
            for (int i = 0; i < file.noeuds.Length; i++)
            {
                if (CircuitLoader.KindOf(file.noeuds[i]) != NodeKind.Nand) continue;
                gates++;
                Vector2 center = CircuitGeometry.Center(file.noeuds[i]);
                Vector2 half = CircuitGeometry.Size(file.noeuds[i]) / 2f;

                Vector2 border = center + new Vector2(0f, half.y + CircuitDrawer.BorderThickness / 2f);
                Assert.AreEqual(NameOfValue(file.etat.noeuds[i]), NearestName(PixelAt(image, border)), "bord de la porte " + file.noeuds[i].id);

                Vector2 body = center + new Vector2(-0.35f, 0.35f);
                Assert.AreEqual("intérieur de porte", NearestName(PixelAt(image, body)), "intérieur de la porte " + file.noeuds[i].id);
            }
            Assert.AreEqual(4, gates);
        }

        [Test]
        public void Render_WiresIntoDifferentSinkPins_ClimbAtDifferentPlaces()
        {
            // Règle vérifiée : décision de la sous-étape 4 (chaque numéro de broche décale le
            // tronçon vertical, pour que les câbles d'une même porte ne se confondent pas).
            // NOT avec A = 0 : les deux câbles partent de A. Celui de la broche 1 descend à
            // x = arrivée - 0,3 - 0,12 ; il n'y a rien à x = arrivée - 0,3 entre y = 0 et la
            // broche 1 (c'est là que descendrait le câble s'il n'était pas décalé).
            CircuitFile file = CircuitLoader.Load(Path.Combine(CircuitsFolder(), "not_A0.json"));
            Texture2D image = Render(file);
            Vector2 sinkOne = CircuitGeometry.SinkPin(file.noeuds[1], 1);
            float middleY = (CircuitGeometry.SourcePin(file.noeuds[0], 0).y + sinkOne.y) / 2f;

            Vector2 shifted = new Vector2(sinkOne.x - CircuitGeometry.WireMargin - CircuitGeometry.SinkStagger, middleY);
            Vector2 notShifted = new Vector2(sinkOne.x - CircuitGeometry.WireMargin, middleY);

            Assert.AreEqual("zéro", NearestName(PixelAt(image, shifted)));
            Assert.AreEqual("fond stable", NearestName(PixelAt(image, notShifted)));
        }

        // --- Le fond -----------------------------------------------------------------

        [Test]
        public void Render_UnstableCircuit_HasAReddishBackdrop()
        {
            // Règle vérifiée : cahier, « Les trois cas détectés » (instable) : Unity le montre
            // par un fond rougeâtre ; un circuit stable a un fond neutre.
            CircuitFile unstable = CircuitLoader.Load(Path.Combine(CircuitsFolder(), "not_reboucle_top1.json"));
            Rect unstableBounds = CircuitGeometry.Bounds(unstable, CircuitDrawer.BackdropMargin);
            Texture2D unstableImage = Render(unstable);
            Vector2 corner = new Vector2(unstableBounds.xMin + 0.1f, unstableBounds.yMin + 0.1f);
            Assert.AreEqual("fond instable", NearestName(PixelAt(unstableImage, corner)));
            UnityEngine.Object.DestroyImmediate(drawn);

            CircuitFile stable = CircuitLoader.Load(Path.Combine(CircuitsFolder(), "not_A0.json"));
            Rect stableBounds = CircuitGeometry.Bounds(stable, CircuitDrawer.BackdropMargin);
            Texture2D stableImage = Render(stable);
            Vector2 stableCorner = new Vector2(stableBounds.xMin + 0.1f, stableBounds.yMin + 0.1f);
            Assert.AreEqual("fond stable", NearestName(PixelAt(stableImage, stableCorner)));
        }

        // --- La structure du dessin --------------------------------------------------

        [Test]
        public void Draw_CreatesOneObjectPerWireAndPerNode()
        {
            // Règle vérifiée : cahier, « Côté Unity » (Dessin crée les portes et les lignes des
            // câbles) : XOR : 7 nœuds, 9 câbles.
            CircuitFile file = CircuitLoader.Load(Path.Combine(CircuitsFolder(), "xor_A1_B0.json"));
            drawn = CircuitDrawer.Draw(file);

            Assert.AreEqual(9, drawn.transform.Find("Wires").childCount);
            Assert.AreEqual(7, drawn.transform.Find("Nodes").childCount);
            Assert.AreEqual(9, drawn.GetComponentsInChildren<LineRenderer>().Length);
        }

        [Test]
        public void Draw_LabelsInputsOutputsAndGates()
        {
            // Règle vérifiée : décision du plan (étiquettes : A, B... pour les entrées, S pour
            // la sortie, NAND pour les portes).
            CircuitFile file = CircuitLoader.Load(Path.Combine(CircuitsFolder(), "xor_A1_B0.json"));
            drawn = CircuitDrawer.Draw(file);

            var labels = new List<string>();
            foreach (TextMesh mesh in drawn.GetComponentsInChildren<TextMesh>()) labels.Add(mesh.text);
            CollectionAssert.AreEqual(new[] { "A", "B", "NAND", "NAND", "NAND", "NAND", "S" }, labels);
        }

        [Test]
        public void Draw_NumbersTheOutputsWhenThereAreSeveral()
        {
            // Règle vérifiée : décision de la sous-étape 4 (S1, S2... quand il y a plusieurs
            // sorties) : la bascule SR a deux sorties.
            CircuitFile file = CircuitLoader.Load(Path.Combine(CircuitsFolder(), "bascule_sr_pas1.json"));
            drawn = CircuitDrawer.Draw(file);

            var labels = new List<string>();
            foreach (TextMesh mesh in drawn.GetComponentsInChildren<TextMesh>()) labels.Add(mesh.text);
            CollectionAssert.AreEqual(new[] { "A", "B", "NAND", "NAND", "S1", "S2" }, labels);
        }

        [Test]
        public void Draw_ComponentNode_ShowsItsNameAndPins()
        {
            // Règle vérifiée : cahier, « Les éléments » (un composant : n puits, m sources).
            string json = ("{'nom': 'TOP', 'noeuds': ["
                + "{'id': 0, 'type': 'ENTREE', 'x': 0, 'y': 0},"
                + "{'id': 1, 'type': 'COMPOSANT', 'x': 2, 'y': 0, 'ref': 'XOR', 'entrees': 3, 'sorties': 2}],"
                + "'cables': [{'de': [0, 0], 'vers': [1, 1]}]}").Replace('\'', '"');
            CircuitFile file = CircuitLoader.Parse(json);
            Texture2D image = Render(file);

            Assert.AreEqual(3, CircuitGeometry.SinkCount(file.noeuds[1]));
            Assert.AreEqual("intérieur de porte", NearestName(PixelAt(image, CircuitGeometry.Center(file.noeuds[1]) + new Vector2(-0.35f, 0.6f))));
            var labels = new List<string>();
            foreach (TextMesh mesh in drawn.GetComponentsInChildren<TextMesh>()) labels.Add(mesh.text);
            CollectionAssert.Contains(labels, "XOR");
        }
    }
}
