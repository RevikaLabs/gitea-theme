#!/usr/bin/env sh
# Builds dist/theme-revika-{dark,light,auto}.css from src/.
set -eu
cd "$(dirname "$0")/.."

# Clear contents, not the directory: dev compose bind-mounts dist/ and would lose a recreated inode.
mkdir -p dist && rm -f dist/*

build() {
  scheme=$1 display=$2
  out=dist/theme-revika-$scheme.css
  {
    printf 'gitea-theme-meta-info {\n  --theme-display-name: "%s";\n  --theme-color-scheme: "%s";\n}\n\n' "$display" "$scheme"
    cat src/fonts.css "src/tokens/gitea-$scheme.base.css" "src/tokens/$scheme.css" src/components/*.css
  } >"$out"
  echo "built $out"
}

build dark "Revika Dark"
if [ -f src/tokens/light.css ]; then
  build light "Revika Light"
  cat >dist/theme-revika-auto.css <<'EOF'
@import "./theme-revika-light.css" (prefers-color-scheme: light);
@import "./theme-revika-dark.css" (prefers-color-scheme: dark);

gitea-theme-meta-info {
  --theme-display-name: "Revika Auto";
  --theme-color-scheme: "auto";
}
EOF
  echo "built dist/theme-revika-auto.css"
fi
