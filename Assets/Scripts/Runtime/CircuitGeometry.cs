using System;
using UnityEngine;

namespace LogicAI
{
    // La géométrie du dessin : tailles, positions des broches, tracé des câbles.
    // Ce sont des fonctions pures (pas d'objet de la scène) : on peut donc les tester sans
    // rien dessiner. Le placement des nœuds, lui, est calculé par Python (x et y du fichier).
    public static class CircuitGeometry
    {
        // Conversion des unités du fichier en unités de Unity. Entre deux colonnes, le
        // fichier compte 2 : cela donne 2,4 unités, pour des boîtes de 1 unité de large.
        public const float XScale = 1.2f;
        public const float YScale = 0.5f;
        public const float BoxWidth = 1.0f;

        // Même règle que Python (layout.box_height) : une boîte fait max(2, broches) unités
        // du fichier de haut, arrondi au pair, avec 1 unité entre deux broches.
        const int MinBoxHeight = 2;

        // Un câble qui revient en arrière sort d'abord un peu à droite, puis passe par un
        // couloir au-dessus des deux broches.
        const float WireMargin = 0.3f;
        const float ChannelOffset = 0.9f;

        public static int SinkCount(NodeData node)
        {
            switch (CircuitLoader.KindOf(node))
            {
                case NodeKind.Input: return 0;
                case NodeKind.Output: return 1;
                case NodeKind.Nand: return 2;
                default: return node.entrees;
            }
        }

        public static int SourceCount(NodeData node)
        {
            switch (CircuitLoader.KindOf(node))
            {
                case NodeKind.Input: return 1;
                case NodeKind.Output: return 0;
                case NodeKind.Nand: return 1;
                default: return node.sorties;
            }
        }

        // La hauteur de la boîte, en unités du fichier.
        public static int BoxHeight(NodeData node)
        {
            int pins = Math.Max(Math.Max(SinkCount(node), SourceCount(node)), MinBoxHeight);
            return pins + pins % 2;
        }

        public static Vector2 Center(NodeData node)
        {
            return new Vector2(node.x * XScale, node.y * YScale);
        }

        public static Vector2 Size(NodeData node)
        {
            return new Vector2(BoxWidth, BoxHeight(node) * YScale);
        }

        // Les broches puits sont sur le bord gauche, la première en haut.
        public static Vector2 SinkPin(NodeData node, int index)
        {
            return Pin(node, index, SinkCount(node), -BoxWidth / 2f);
        }

        // Les broches sources sont sur le bord droit, la première en haut.
        public static Vector2 SourcePin(NodeData node, int index)
        {
            return Pin(node, index, SourceCount(node), BoxWidth / 2f);
        }

        static Vector2 Pin(NodeData node, int index, int count, float xOffset)
        {
            Vector2 center = Center(node);
            float y = center.y + ((count - 1) / 2f - index) * YScale;
            return new Vector2(center.x + xOffset, y);
        }

        // Le tracé d'un câble, de la broche source à la broche puits : des segments
        // horizontaux et verticaux seulement.
        public static Vector2[] Route(Vector2 start, Vector2 end)
        {
            bool goesForward = end.x - start.x >= 2f * WireMargin;
            if (goesForward)
            {
                if (Mathf.Approximately(start.y, end.y))
                {
                    return new[] { start, end };
                }
                float middle = (start.x + end.x) / 2f;
                return new[] { start, new Vector2(middle, start.y), new Vector2(middle, end.y), end };
            }
            float channel = Mathf.Max(start.y, end.y) + ChannelOffset;
            return new[]
            {
                start,
                new Vector2(start.x + WireMargin, start.y),
                new Vector2(start.x + WireMargin, channel),
                new Vector2(end.x - WireMargin, channel),
                new Vector2(end.x - WireMargin, end.y),
                end,
            };
        }

        // Le rectangle qui contient toutes les boîtes, agrandi de « margin » (pour cadrer la
        // caméra). Un circuit vide donne un petit rectangle centré sur l'origine.
        public static Rect Bounds(CircuitFile file, float margin)
        {
            if (file.noeuds == null || file.noeuds.Length == 0)
            {
                return new Rect(-margin, -margin, 2f * margin, 2f * margin);
            }
            float xMin = float.MaxValue, yMin = float.MaxValue;
            float xMax = float.MinValue, yMax = float.MinValue;
            foreach (NodeData node in file.noeuds)
            {
                Vector2 center = Center(node);
                Vector2 half = Size(node) / 2f;
                xMin = Mathf.Min(xMin, center.x - half.x);
                xMax = Mathf.Max(xMax, center.x + half.x);
                yMin = Mathf.Min(yMin, center.y - half.y);
                yMax = Mathf.Max(yMax, center.y + half.y);
            }
            return Rect.MinMaxRect(xMin - margin, yMin - margin, xMax + margin, yMax + margin);
        }
    }
}
