using UnityEngine;

namespace LogicAI
{
    // Les couleurs du dessin. Un câble à 0 est bleu-gris, un câble à 1 est jaune vif, et un
    // câble dont on ne connaît pas la valeur (fichier sans « etat ») est gris clair.
    public static class CircuitPalette
    {
        public static readonly Color Zero = new Color(0.33f, 0.40f, 0.55f);
        public static readonly Color One = new Color(1.00f, 0.82f, 0.25f);
        public static readonly Color Unknown = new Color(0.62f, 0.63f, 0.66f);

        // L'intérieur d'une porte, ses broches, et les fonds : stable ou instable.
        public static readonly Color NodeFill = new Color(0.16f, 0.18f, 0.24f);
        public static readonly Color Pin = new Color(0.85f, 0.85f, 0.88f);
        public static readonly Color BackdropStable = new Color(0.10f, 0.11f, 0.15f);
        public static readonly Color BackdropUnstable = new Color(0.30f, 0.10f, 0.10f);

        // Le texte : clair sur une porte sombre, foncé sur une entrée ou une sortie colorée.
        public static readonly Color LabelOnDark = new Color(0.92f, 0.93f, 0.96f);
        public static readonly Color LabelOnValue = new Color(0.05f, 0.05f, 0.08f);

        // La couleur d'une valeur du fichier : 0, 1, ou inconnue (-1 ou tout autre nombre).
        public static Color ForValue(int value)
        {
            if (value == 0) return Zero;
            if (value == 1) return One;
            return Unknown;
        }
    }
}
