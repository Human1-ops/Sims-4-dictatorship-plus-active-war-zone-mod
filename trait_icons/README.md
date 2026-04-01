# Virtual Trait Custom Images

This directory contains the custom icon images for the 5 new Virtual Traits introduced in the Dictatorship Mod Prototype:
1. `true_believer.png` ("True Believer" / Loyalist)
2. `paranoid.png` (Paranoid)
3. `submissive.png` (Submissive)
4. `dissident.png` (Dissident / Revolutionary)
5. `opportunist.png` (Opportunist)

## Important Note Regarding The Sims 4 Image Modding

In The Sims 4 engine, dropping `.png` images into your `Mods` folder does **not** automatically link them to custom traits. The game's UI relies exclusively on `.dds` (DirectDraw Surface) image textures packaged within `.package` files, which are heavily indexed using specialized FNV-32 XML tuning IDs.

Because this project is currently a **Pure Python Script Prototype** (packaged as a `.ts4script` archive) and lacks customized XML tuning files, these trait icons cannot be injected directly via Python.

### How to use these icons in a final release:

To implement these custom images in your final mod, you must:
1. Open [Sims 4 Studio](https://sims4studio.com/).
2. Create new Trait XML Tuning files for each of the 5 traits.
3. Import these 5 `.png` images as DST Image resources. Sims 4 Studio will automatically compress them into `DXT5/BC3 .dds` formats and assign them a unique FNV-32 Instance ID.
4. Link the new 32-bit Image Instance IDs to the `icon` field within your custom Trait XML Tuning files.
5. Export as a `.package` file and distribute it alongside your `.ts4script` logic.