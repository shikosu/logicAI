using System.Collections.Generic;
using UnityEngine;

namespace LogicAI
{
    // Dessine un circuit dans la scène : un fond, des câbles (LineRenderer) colorés selon
    // leur valeur 0/1, et des portes (sprites). Unity ne calcule rien : positions et
    // valeurs viennent du fichier écrit par Python.
    public static class CircuitDrawer
    {
        // Valeur à utiliser quand le fichier n'a pas d'« etat ».
        public const int NoValue = -1;

        // Épaisseurs, en unités Unity.
        public const float BorderThickness = 0.08f;
        public const float WireWidth = 0.07f;
        const float PinSize = 0.12f;
        public const float BackdropMargin = 0.6f;
        const float LabelCharacterSize = 0.055f;
        const int LabelFontSize = 48;

        // L'ordre d'empilement : le fond derrière, puis les câbles, les portes, les broches.
        const int BackdropOrder = 0;
        const int WireOrder = 1;
        const int NodeOrder = 2;
        const int PinOrder = 3;
        const int LabelOrder = 4;

        // Un carré blanc de 1 unité, teinté et mis à l'échelle pour chaque boîte.
        static Sprite whiteSquare;
        static Material unlitSpriteMaterial;

        // Dessine le circuit et renvoie l'objet racine (à détruire pour effacer le dessin).
        public static GameObject Draw(CircuitFile file)
        {
            var root = new GameObject("Circuit " + file.nom);
            Material material = UnlitMaterial();
            bool hasState = CircuitLoader.HasState(file);
            NodeData[] nodes = file.noeuds ?? new NodeData[0];
            WireData[] wires = file.cables ?? new WireData[0];

            DrawBackdrop(root.transform, file, hasState && !file.etat.stable, material);

            var nodesById = new Dictionary<int, NodeData>();
            foreach (NodeData node in nodes) nodesById[node.id] = node;

            Transform wiresParent = NewChild(root.transform, "Wires");
            for (int i = 0; i < wires.Length; i++)
            {
                int value = hasState ? file.etat.cables[i] : NoValue;
                DrawWire(wiresParent, wires[i], nodesById, value, material);
            }

            Transform nodesParent = NewChild(root.transform, "Nodes");
            int inputIndex = 0, outputIndex = 0;
            for (int i = 0; i < nodes.Length; i++)
            {
                int value = hasState ? file.etat.noeuds[i] : NoValue;
                string label = LabelOf(nodes[i], ref inputIndex, ref outputIndex, CountOutputs(nodes));
                DrawNode(nodesParent, nodes[i], value, label, material);
            }
            return root;
        }

        // --- Le fond -----------------------------------------------------------------

        static void DrawBackdrop(Transform parent, CircuitFile file, bool unstable, Material material)
        {
            Rect bounds = CircuitGeometry.Bounds(file, BackdropMargin);
            Color color = unstable ? CircuitPalette.BackdropUnstable : CircuitPalette.BackdropStable;
            NewBox("Backdrop", parent, bounds.center, bounds.size, color, BackdropOrder, material);
        }

        // --- Les câbles --------------------------------------------------------------

        static void DrawWire(Transform parent, WireData wire, Dictionary<int, NodeData> nodesById, int value, Material material)
        {
            NodeData from = nodesById[wire.de[0]];
            NodeData to = nodesById[wire.vers[0]];
            Vector2[] route = CircuitGeometry.Route(
                CircuitGeometry.SourcePin(from, wire.de[1]),
                CircuitGeometry.SinkPin(to, wire.vers[1]),
                wire.vers[1]);

            var line = NewChild(parent, "Wire " + wire.de[0] + "." + wire.de[1] + " -> " + wire.vers[0] + "." + wire.vers[1])
                .gameObject.AddComponent<LineRenderer>();
            Color color = CircuitPalette.ForValue(value);
            line.sharedMaterial = material;
            line.startColor = color;
            line.endColor = color;
            line.widthMultiplier = WireWidth;
            line.numCornerVertices = 3;
            line.sortingOrder = WireOrder;
            line.useWorldSpace = true;
            line.positionCount = route.Length;
            for (int i = 0; i < route.Length; i++)
            {
                line.SetPosition(i, new Vector3(route[i].x, route[i].y, 0f));
            }
        }

        // --- Les portes --------------------------------------------------------------

        static void DrawNode(Transform parent, NodeData node, int value, string label, Material material)
        {
            Transform holder = NewChild(parent, label);
            Vector2 center = CircuitGeometry.Center(node);
            Vector2 size = CircuitGeometry.Size(node);
            NodeKind kind = CircuitLoader.KindOf(node);
            Color valueColor = CircuitPalette.ForValue(value);

            bool isTerminal = kind == NodeKind.Input || kind == NodeKind.Output;
            if (isTerminal)
            {
                // Une entrée ou une sortie du circuit est remplie de la couleur de sa valeur.
                NewBox("Body", holder, center, size, valueColor, NodeOrder, material);
            }
            else
            {
                // Une porte a un intérieur sombre et un bord de la couleur de sa valeur.
                NewBox("Border", holder, center, size + Vector2.one * (2f * BorderThickness), valueColor, NodeOrder, material);
                NewBox("Body", holder, center, size, CircuitPalette.NodeFill, NodeOrder + 1, material);
            }

            for (int i = 0; i < CircuitGeometry.SinkCount(node); i++)
            {
                NewBox("Sink " + i, holder, CircuitGeometry.SinkPin(node, i), Vector2.one * PinSize, CircuitPalette.Pin, PinOrder, material);
            }
            for (int i = 0; i < CircuitGeometry.SourceCount(node); i++)
            {
                NewBox("Source " + i, holder, CircuitGeometry.SourcePin(node, i), Vector2.one * PinSize, CircuitPalette.Pin, PinOrder, material);
            }

            Color labelColor = isTerminal ? CircuitPalette.LabelOnValue : CircuitPalette.LabelOnDark;
            NewLabel(holder, center, label, labelColor);
        }

        // Le texte d'une porte : A, B... pour les entrées, S pour les sorties, NAND ou le nom
        // du composant sinon.
        static string LabelOf(NodeData node, ref int inputIndex, ref int outputIndex, int outputCount)
        {
            switch (CircuitLoader.KindOf(node))
            {
                case NodeKind.Input:
                    return ((char)('A' + inputIndex++)).ToString();
                case NodeKind.Output:
                    outputIndex++;
                    return outputCount > 1 ? "S" + outputIndex : "S";
                case NodeKind.Nand:
                    return "NAND";
                default:
                    return node.@ref;
            }
        }

        static int CountOutputs(NodeData[] nodes)
        {
            int count = 0;
            foreach (NodeData node in nodes)
            {
                if (CircuitLoader.KindOf(node) == NodeKind.Output) count++;
            }
            return count;
        }

        // --- Outils ------------------------------------------------------------------

        static Transform NewChild(Transform parent, string name)
        {
            var child = new GameObject(name).transform;
            child.SetParent(parent, false);
            return child;
        }

        static void NewBox(string name, Transform parent, Vector2 center, Vector2 size, Color color, int order, Material material)
        {
            Transform box = NewChild(parent, name);
            box.localPosition = new Vector3(center.x, center.y, 0f);
            box.localScale = new Vector3(size.x, size.y, 1f);
            var renderer = box.gameObject.AddComponent<SpriteRenderer>();
            renderer.sprite = WhiteSquare();
            renderer.sharedMaterial = material;
            renderer.color = color;
            renderer.sortingOrder = order;
        }

        static void NewLabel(Transform parent, Vector2 center, string text, Color color)
        {
            Transform holder = NewChild(parent, "Label");
            holder.localPosition = new Vector3(center.x, center.y, 0f);
            var mesh = holder.gameObject.AddComponent<TextMesh>();
            Font font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            mesh.font = font;
            mesh.text = text;
            mesh.anchor = TextAnchor.MiddleCenter;
            mesh.alignment = TextAlignment.Center;
            mesh.fontSize = LabelFontSize;
            mesh.characterSize = LabelCharacterSize;
            mesh.color = color;
            var renderer = holder.GetComponent<MeshRenderer>();
            renderer.sharedMaterial = font.material;
            renderer.sortingOrder = LabelOrder;
        }

        // Les objets partagés sont créés une seule fois. « == null » détecte aussi un objet que
        // Unity a détruit (par exemple au rechargement des scripts).
        static Sprite WhiteSquare()
        {
            if (whiteSquare == null)
            {
                var texture = new Texture2D(1, 1, TextureFormat.RGBA32, false);
                texture.SetPixel(0, 0, Color.white);
                texture.Apply();
                texture.hideFlags = HideFlags.HideAndDontSave;
                whiteSquare = Sprite.Create(texture, new Rect(0, 0, 1, 1), new Vector2(0.5f, 0.5f), 1f);
                whiteSquare.hideFlags = HideFlags.HideAndDontSave;
            }
            return whiteSquare;
        }

        static Material UnlitMaterial()
        {
            if (unlitSpriteMaterial == null)
            {
                unlitSpriteMaterial = new Material(Shader.Find("Sprites/Default"));
                unlitSpriteMaterial.hideFlags = HideFlags.HideAndDontSave;
            }
            return unlitSpriteMaterial;
        }
    }
}
