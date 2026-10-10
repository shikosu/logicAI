#!/bin/zsh
# Lance les tests Unity en ligne de commande, sur une COPIE du projet.
#
# Pourquoi une copie : quand l'éditeur Unity est ouvert sur le projet, Unity refuse de
# l'ouvrir une 2e fois. La copie (Assets, Packages, ProjectSettings, circuits) est faite
# dans un dossier temporaire ; la première exécution l'importe en une quarantaine de
# secondes, les suivantes vont plus vite. Le vrai projet n'est jamais modifié.
#
# Usage : tools/run_unity_tests.sh [EditMode|PlayMode]      (EditMode par défaut)
# Pour écrire une image PNG par circuit dessiné (tests de rendu) :
#   LOGICAI_RENDER_DIR=/chemin/dossier tools/run_unity_tests.sh
set -u

PLATFORM=${1:-EditMode}
ROOT=${0:A:h:h}                       # racine du projet : le dossier qui contient tools/
VERSION=$(sed -n 's/^m_EditorVersion: //p' "$ROOT/ProjectSettings/ProjectVersion.txt")
UNITY="/Applications/Unity/Hub/Editor/$VERSION/Unity.app/Contents/MacOS/Unity"
COPY=${LOGICAI_UNITY_COPY:-${TMPDIR:-/tmp}/logicai_unity_copy}
LOGS=${COPY}_logs

if [[ ! -x "$UNITY" ]]; then
  echo "Unity $VERSION introuvable : $UNITY" >&2
  exit 2
fi
case "$COPY" in
  "$ROOT"|"$ROOT"/*) echo "Le dossier de copie ne doit pas être dans le projet : $COPY" >&2; exit 2 ;;
esac

mkdir -p "$COPY" "$LOGS"
# Les .meta de la copie sont ceux que Unity y génère lui-même : on ne les écrase pas.
for folder in Assets Packages ProjectSettings circuits; do
  rsync -a --delete --exclude='*.meta' "$ROOT/$folder/" "$COPY/$folder/"
done

rm -f "$LOGS/results.xml" "$LOGS/unity.log"
"$UNITY" -batchmode -projectPath "$COPY" -runTests -testPlatform "$PLATFORM" \
  -testResults "$LOGS/results.xml" -logFile "$LOGS/unity.log" > /dev/null 2>&1
unity_status=$?

if [[ ! -f "$LOGS/results.xml" ]]; then
  echo "Pas de résultat (erreur de compilation ?). Journal : $LOGS/unity.log" >&2
  grep -E "error CS" "$LOGS/unity.log" | sort -u | head -10 >&2
  exit 1
fi

"$ROOT/python/.venv/bin/python" -I - "$LOGS/results.xml" <<'PY'
import sys, xml.etree.ElementTree as ET
root = ET.parse(sys.argv[1]).getroot()
print("Tests Unity :", {k: root.get(k) for k in ("total", "passed", "failed", "skipped")})
for case in root.iter("test-case"):
    if case.get("result") != "Passed":
        failure = case.find("failure")
        message = failure.findtext("message") if failure is not None else ""
        print("  ÉCHEC :", case.get("fullname"), "->", (message or "").strip().replace("\n", " ")[:300])
PY
exit $unity_status
