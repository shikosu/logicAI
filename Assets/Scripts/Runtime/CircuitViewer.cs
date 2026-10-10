using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace LogicAI
{
    // Le visualiseur : au lancement du mode Play, il lit les fichiers du dossier circuits/ (à
    // la racine du projet), affiche une liste cliquable et dessine le circuit choisi.
    //
    // Il démarre tout seul (RuntimeInitializeOnLoadMethod) : aucune modification de la scène
    // n'est nécessaire. C'est un outil de la phase 3 ; en phase 5, les circuits arriveront
    // par le socket.
    public class CircuitViewer : MonoBehaviour
    {
        // Le dossier lu. Vide = le dossier circuits/ à la racine du projet.
        public string folder = "";

        // La largeur, en pixels, de la liste à gauche : la caméra ne dessine pas dessous.
        const float PanelWidth = 240f;
        const float Margin = 1.2f;

        readonly List<string> files = new List<string>();
        GameObject drawn;
        int selected = -1;
        int lastScreenWidth;
        Vector2 scroll;

        public IReadOnlyList<string> Files { get { return files; } }
        public CircuitFile Current { get; private set; }
        public string ErrorMessage { get; private set; }

        // Crée le visualiseur au lancement du Play, s'il n'y en a pas déjà un.
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
            if (FindFirstObjectByType<CircuitViewer>() == null)
            {
                new GameObject("CircuitViewer").AddComponent<CircuitViewer>();
            }
        }

        public static string DefaultFolder()
        {
            return Path.GetFullPath(Path.Combine(Application.dataPath, "..", "circuits"));
        }

        void Start()
        {
            Refresh();
            if (files.Count > 0) Select(0);
        }

        void Update()
        {
            // La liste occupe une largeur fixe en pixels : on recadre si la fenêtre change.
            if (Screen.width != lastScreenWidth && Current != null)
            {
                lastScreenWidth = Screen.width;
                FitCamera();
            }
        }

        // Relit la liste des fichiers du dossier.
        public void Refresh()
        {
            files.Clear();
            string path = string.IsNullOrEmpty(folder) ? DefaultFolder() : folder;
            if (!Directory.Exists(path))
            {
                ErrorMessage = "dossier introuvable : " + path;
                return;
            }
            files.AddRange(Directory.GetFiles(path, "*.json"));
            files.Sort(StringComparer.Ordinal);
            ErrorMessage = files.Count == 0 ? "aucun fichier .json dans " + path : null;
        }

        // Charge et dessine le fichier numéro « index » de la liste. Un fichier invalide ne
        // plante rien : le message d'erreur est gardé pour être affiché.
        public void Select(int index)
        {
            if (index < 0 || index >= files.Count) return;
            selected = index;
            ClearDrawing();
            try
            {
                Current = CircuitLoader.Load(files[index]);
                ErrorMessage = null;
                drawn = CircuitDrawer.Draw(Current);
                FitCamera();
            }
            catch (CircuitFormatException exception)
            {
                Current = null;
                ErrorMessage = exception.Message;
            }
        }

        void ClearDrawing()
        {
            if (drawn == null) return;
            if (Application.isPlaying) Destroy(drawn);
            else DestroyImmediate(drawn);
            drawn = null;
        }

        void OnDestroy()
        {
            ClearDrawing();
        }

        void FitCamera()
        {
            Camera camera = Camera.main;
            if (camera == null || Current == null) return;
            // La caméra ne dessine que la partie à droite de la liste.
            float fraction = Mathf.Clamp01(PanelWidth / Mathf.Max(Screen.width, 1));
            camera.rect = new Rect(fraction, 0f, 1f - fraction, 1f);
            Vector2 center;
            float size;
            CircuitGeometry.FitCamera(CircuitGeometry.Bounds(Current, Margin), camera.aspect, out center, out size);
            camera.orthographic = true;
            camera.orthographicSize = size;
            camera.transform.position = new Vector3(center.x, center.y, camera.transform.position.z);
        }

        // --- Interface minimale (IMGUI : fonctionne avec le nouveau système d'entrée) ----

        void OnGUI()
        {
            GUILayout.BeginArea(new Rect(0f, 0f, PanelWidth, Screen.height), GUI.skin.box);
            GUILayout.Label("Circuits (" + files.Count + ")");
            scroll = GUILayout.BeginScrollView(scroll);
            for (int i = 0; i < files.Count; i++)
            {
                string name = Path.GetFileNameWithoutExtension(files[i]);
                bool isCurrent = i == selected;
                if (GUILayout.Toggle(isCurrent, name, GUI.skin.button) && !isCurrent)
                {
                    Select(i);
                }
            }
            GUILayout.EndScrollView();
            GUILayout.EndArea();

            string status = StatusLine();
            if (status != null)
            {
                GUI.Label(new Rect(PanelWidth + 10f, 8f, Screen.width - PanelWidth - 20f, 24f), status);
            }
        }

        // Le résumé affiché en haut : nom, top, stabilité ; ou le message d'erreur.
        string StatusLine()
        {
            if (!string.IsNullOrEmpty(ErrorMessage)) return "ERREUR : " + ErrorMessage;
            if (Current == null) return null;
            if (!CircuitLoader.HasState(Current)) return Current.nom + " (sans valeurs)";
            string stability = Current.etat.stable ? "stable" : "INSTABLE";
            return Current.nom + " - top " + Current.etat.top + " - " + stability;
        }
    }
}
