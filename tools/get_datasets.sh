#!/usr/bin/env bash
# Datasets in data/, archived on Google Drive (docs/data-drive.md).
#
#   tools/get_datasets.sh check                      status of every dataset (nothing downloaded)
#   tools/get_datasets.sh ready <ds>…                exit code 0 if all are ready
#   tools/get_datasets.sh download <ds>…             direct download (only datasets with a hook)
#   tools/get_datasets.sh pack <ds>…                 data/<root> → data_archives/<ds>.tar
#   tools/get_datasets.sh unpack <dir> <ds>…         <dir>/<ds>.tar → data/ (Colab: mounted Drive)
#   tools/get_datasets.sh push <ds>…                 pack, then rclone to $DRIVE_REMOTE
#   tools/get_datasets.sh pull <ds>…                 if missing: rclone from $DRIVE_REMOTE, unpack
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${DATA_DIR:-$ROOT/data}"                 # overridden by the tests
ARCHIVE_DIR="${ARCHIVE_DIR:-$ROOT/data_archives}"
DRIVE_REMOTE="${DRIVE_REMOTE:-gdrive:SerreIA/data}"  # rclone remote of the archives

# One marker per dataset, relative to data/: present ⇔ the dataset is ready (docs/data-drive.md).
declare -A MARKER=(
  [index]="index.parquet"
  [plantvillage]="plantvillage/segmented/Tomato___healthy"
  [ccmt]="ccmt/raw/Tomato/healthy"
  [plantdoc]="plantdoc/crops/test"
  [backgrounds]="backgrounds"
)
# Paths under data/ archived for the dataset, when they differ from its name (default: the
# name). Several paths are separated by spaces.
declare -A DIR=(
  [index]="index.parquet index_rejets.txt"
  [ccmt]="ccmt/raw"
)
# Paths left out of the archive (unused by the code).
declare -A EXCLUDE=(
  [plantvillage]="plantvillage/grayscale"
)

known() {
  [[ -n "${MARKER[$1]:-}" ]] || { echo "unknown dataset: $1 (known: ${!MARKER[*]})" >&2; exit 1; }
}

check() {
  local ds=$1
  if [[ -e "$DATA_DIR/${MARKER[$ds]}" ]]; then
    echo "$ds: ready (${MARKER[$ds]})"
  else
    echo "$ds: missing (${MARKER[$ds]})"
    return 1
  fi
}

# Direct download of a dataset, when one exists (idempotent: skip if the marker is there).
# Add one case per downloadable dataset; the others only come from the Drive.
download() {
  local ds=$1
  check "$ds" > /dev/null && { echo "$ds: already ready"; return 0; }
  case "$ds" in
    # Sources fetched by hand then prepared (docs/02-donnees.md): only the Drive serves them.
    *) echo "$ds: no direct download, use: $0 pull $ds" >&2; return 1 ;;
  esac
  check "$ds"
}

# Archive of a ready dataset: one uncompressed tar (images are already compressed), links
# followed (-h) so the expected tree holds without the original folders; downloaded
# archives and partial files stay out. Written as .part then renamed: a .tar is complete.
pack() {
  local ds=$1 dir=${DIR[$1]:-$1} ex
  local -a paths excludes=()
  read -ra paths <<< "$dir"
  for ex in ${EXCLUDE[$ds]:-}; do excludes+=("--exclude=$ex"); done
  check "$ds" > /dev/null || { echo "$ds: missing, nothing to archive" >&2; return 1; }
  mkdir -p "$ARCHIVE_DIR"
  echo "archiving data/{${paths[*]}} → $ARCHIVE_DIR/$ds.tar"
  tar -chf "$ARCHIVE_DIR/$ds.tar.part" -C "$DATA_DIR" --exclude='*.zip' --exclude='*.part' \
    --exclude='*.tar' --exclude=__MACOSX "${excludes[@]}" "${paths[@]}"
  mv "$ARCHIVE_DIR/$ds.tar.part" "$ARCHIVE_DIR/$ds.tar"
}

# Extraction from a folder of archives (mounted Drive on Colab): one sequential read of
# the tar, then the files are read from the local disk, never through the mount.
unpack() {
  local src=$1 ds=$2
  if check "$ds" > /dev/null; then
    echo "$ds: already ready"
    return 0
  fi
  [[ -f "$src/$ds.tar" ]] || { echo "$ds: no archive $src/$ds.tar" >&2; return 1; }
  mkdir -p "$DATA_DIR"
  echo "extracting $src/$ds.tar"
  tar -xf "$src/$ds.tar" -C "$DATA_DIR"
  check "$ds"
}

need_rclone() {
  local remote=${DRIVE_REMOTE%%:*}
  command -v rclone > /dev/null || {
    echo "rclone missing: sudo apt install rclone, then rclone config create $remote drive scope=drive" >&2
    return 1
  }
  rclone listremotes | grep -qx "$remote:" || {
    echo "remote $remote missing: rclone config create $remote drive scope=drive" >&2
    return 1
  }
}

# Export of a ready dataset to Google Drive (PC); the archive stays in data_archives/.
push() {
  local ds=$1
  need_rclone || return 1
  pack "$ds"
  echo "uploading $ARCHIVE_DIR/$ds.tar → $DRIVE_REMOTE"
  rclone copy "$ARCHIVE_DIR/$ds.tar" "$DRIVE_REMOTE" --progress
}

# Dataset missing locally: its archive is fetched from Google Drive, then extracted.
# Never replaces a dataset that is already present.
pull() {
  local ds=$1
  if check "$ds" > /dev/null; then
    echo "$ds: already ready"
    return 0
  fi
  need_rclone || return 1
  mkdir -p "$ARCHIVE_DIR"
  echo "fetching $DRIVE_REMOTE/$ds.tar → $ARCHIVE_DIR"
  rclone copy "$DRIVE_REMOTE/$ds.tar" "$ARCHIVE_DIR" --progress || return 1
  unpack "$ARCHIVE_DIR" "$ds"
}

[[ $# -gt 0 ]] || { sed -n '2,10p' "$0"; exit 1; }
cmd=$1; shift
case "$cmd" in
check)
  for ds in "${!MARKER[@]}"; do check "$ds" || true; done
  ;;
ready)
  for ds in "$@"; do known "$ds"; check "$ds" || exit 1; done
  ;;
download | pack | push | pull)
  status=0
  for ds in "$@"; do known "$ds"; "$cmd" "$ds" || status=1; done
  exit $status
  ;;
unpack)
  [[ $# -ge 2 ]] || { echo "usage: $0 unpack <dir> <ds>…" >&2; exit 1; }
  src=$1; shift
  status=0
  for ds in "$@"; do known "$ds"; unpack "$src" "$ds" || status=1; done
  exit $status
  ;;
*)
  echo "unknown command: $cmd" >&2; sed -n '2,10p' "$0"; exit 1
  ;;
esac
