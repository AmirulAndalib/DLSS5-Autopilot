# DLSS 5 in a headset

Short version: the tool can put the neural pass where the headset looks, and
nobody here has been able to watch it happen. This page says exactly what
runs, what is registered on your PC, and what is still unproven, so a report
from somebody with a headset can settle it.

## Why a proxy DLL is not enough

A VR game on **OpenXR** draws two eye images through the OpenXR runtime. The
window on your desktop is a mirror of that - a copy, drawn after the fact.

- A proxy DLL (`dxgi.dll`, `d3d11.dll`) or the Vulkan layer hooks the game's
  own device, which draws the **mirror**. The pass runs, the desktop window
  changes, and the headset sees nothing (issue #33).
- ReShade 6 also ships an **OpenXR API layer** (`ReShade64_XR.json`, loading
  the same `ReShade64.dll`). That layer hooks the OpenXR swapchain - the
  picture the eyes get.

So VR needs the OpenXR layer, not a DLL beside the executable.

Games on **OpenVR / SteamVR** are not reached by this layer at all. If the
game only offers SteamVR, nothing here applies to it.

## What the tool does

Tick **VR headset (OpenXR layer)** in a 64-bit game's settings and install.
On top of the route's own files, the install:

1. extracts `ReShade64.dll` and `ReShade64_XR.json` next to the Vulkan layer
   files this tool keeps for you;
2. registers the manifest for **your user account**:

   ```
   HKCU\Software\Khronos\OpenXR\1\ApiLayers\Implicit
       <path>\ReShade64_XR.json  =  (DWORD) 0
   ```

That registration is **global for your user**, like the Vulkan layer: once it
is there, ReShade loads into every OpenXR application you start, not only the
game you installed from. A registration made by ReShade's own installer is
reused and never rewritten.

The **vr** page in the window shows whether a layer is registered and whose
it is, lists the games in your library that carry OpenXR's own loader
(`openxr_loader.dll` - the only evidence read from disk that a game goes
through OpenXR), and has the one button that takes **our** registration out
again. Uninstalling the last VR install removes it too.

## What is proven, and what is not

| | |
|---|---|
| the layer registers, the files land, uninstall removes it | runs here, in the suite and by hand |
| the feeder / bridge / DLSS 5 add-on inside an OpenXR swapchain | **never tried in a headset** - there is none on this machine |
| SteamVR-only titles | out of reach of this layer |

If you have a headset: install with the box ticked, play, and press **did it
work?** or share the result. That report goes into the same shared list as
every other one, and it is the only thing that can turn the table above into
an answer.

## If it does not work

- Check the **vr** page first: if it says *not registered*, the install never
  got that far - the log drawer will say why (`ReShade64.dll` in use by a
  running Vulkan or OpenXR program is the usual one; close SteamVR and the
  headset's own software and install again).
- `ReShade.log` beside the game says which layer loaded. No log at all means
  nothing of ours was ever loaded (see the README's diagnosis notes).
- One layer per user: if another tool registered its own copy of ReShade's
  OpenXR layer, ours is not added on top - the page names the file that is
  registered so you can decide which to keep.
