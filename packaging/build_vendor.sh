#!/usr/bin/env bash
# Run on the target CPU. Build prerequisites are installed by build-release.yml.
set -euo pipefail
cd "$(dirname "$0")/.."
build_root="$PWD"
report_failure() {
  status=$?
  for log in "$build_root/vendor/build/x264/config.log" "$build_root/vendor/build/ffmpeg/ffbuild/config.log"; do
    if [ -f "$log" ]; then tail -n 80 "$log"; fi
  done
  exit "$status"
}
trap report_failure ERR
# Keep this array nonempty: macOS's Bash 3.2 treats an empty array as unset
# when expanding it under `set -u`.
x264_options=(--enable-static --enable-pic --disable-cli --disable-asm)
if [ "${MSYSTEM:-}" = CLANGARM64 ]; then
  # MSYS runs an x64 shell on ARM64; x264's default gcc can select a host x64
  # compiler from the inherited runner PATH even when CMake/Meson use ARM64.
  export CC=clang CXX=clang++ AR=llvm-ar RANLIB=llvm-ranlib
  x264_options+=(--host=aarch64-w64-mingw32)
fi
pycmd=${FLINTEYE_PYTHON:-python}
if command -v cygpath >/dev/null; then
  pycmd=$(cygpath -u "$pycmd")
  # Native Meson may find Strawberry Perl's incompatible pkg-config.bat on
  # the inherited Windows PATH. Select the active CPU's MSYS2 pkgconf by path.
  # https://www.msys2.org/docs/pkgconfig/
  native_pkgconf="${MINGW_PREFIX:?Use the UCRT64 or CLANGARM64 MSYS2 shell}/bin/pkgconf.exe"
  if [ ! -x "$native_pkgconf" ]; then
    printf 'Install pkgconf for the active MSYS2 environment: %s\n' "$MINGW_PREFIX" >&2
    exit 1
  fi
  export PATH="$MINGW_PREFIX/bin:$PATH"
  export PKG_CONFIG="$(cygpath -m "$native_pkgconf")"
  "$native_pkgconf" --version
fi
"$pycmd" packaging/vendor.py fetch ffmpeg x264 freetype harfbuzz mediamtx
mkdir -p vendor/prefix vendor/build vendor/bin
prefix="$PWD/vendor/prefix"
if command -v cygpath >/dev/null; then prefix=$(cygpath -m "$prefix"); fi
export PKG_CONFIG_PATH="$prefix/lib/pkgconfig"
jobs=${FLINTEYE_BUILD_JOBS:-4}
cmake -S vendor/src/freetype -B vendor/build/freetype -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DCMAKE_INSTALL_PREFIX="$prefix" \
  -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DFT_DISABLE_ZLIB=TRUE -DFT_DISABLE_BZIP2=TRUE \
  -DFT_DISABLE_PNG=TRUE -DFT_DISABLE_HARFBUZZ=TRUE -DFT_DISABLE_BROTLI=TRUE
cmake --build vendor/build/freetype --parallel "$jobs"
cmake --install vendor/build/freetype
"${PKG_CONFIG:-pkg-config}" --print-errors --exists --static freetype2
meson setup vendor/build/harfbuzz vendor/src/harfbuzz --prefix="$prefix" --libdir=lib \
  --buildtype=release --default-library=static -Dfreetype=enabled -Dglib=disabled \
  -Dgobject=disabled -Dicu=disabled -Dcairo=disabled -Dtests=disabled -Ddocs=disabled \
  -Dintrospection=disabled -Dutilities=disabled
meson compile -C vendor/build/harfbuzz -j "$jobs"
meson install -C vendor/build/harfbuzz
root="$PWD"
cd vendor/build
mkdir -p x264 ffmpeg
cd x264
# Portable fallback: avoid an architecture-specific assembler dependency.
../../src/x264/configure --prefix="$prefix" "${x264_options[@]}"
make -j "$jobs"
make install
cd ../ffmpeg
extra=()
case "$(uname -s)" in
  Darwin)
    extra+=(--enable-securetransport --enable-videotoolbox --enable-audiotoolbox --enable-avfoundation)
    ;;
  MINGW*|MSYS*|CYGWIN*)
    extra+=(--enable-schannel --extra-ldflags=-static)
    if [ "${MSYSTEM:-}" = CLANGARM64 ]; then
      extra+=(--arch=aarch64 --target-os=mingw32 --cc=clang --cxx=clang++ --disable-asm)
    fi
    ;;
  Linux)
    # OpenSSL 3 + GPLv2-or-later x264 requires the GPLv3 combination.
    extra+=(--enable-openssl --enable-version3 --extra-ldflags=-static-libstdc++)
    ;;
  *) printf 'Unsupported build host\n' >&2; exit 1 ;;
esac
../../src/ffmpeg/configure --prefix="$prefix" --disable-shared --enable-static \
  --disable-autodetect --disable-doc --disable-debug --disable-ffplay --enable-gpl \
  --enable-libx264 --enable-libfreetype --enable-libharfbuzz --enable-network \
  --pkg-config="${PKG_CONFIG:-pkg-config}" --pkg-config-flags=--static --extra-cflags="-I$prefix/include" "${extra[@]}"
make -j "$jobs"
make install
cd "$root"
suffix=''
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) suffix=.exe ;; esac
cp "$prefix/bin/ffmpeg$suffix" "$prefix/bin/ffprobe$suffix" vendor/bin/
"$pycmd" packaging/vendor.py mediamtx
"$pycmd" packaging/vendor.py finish
