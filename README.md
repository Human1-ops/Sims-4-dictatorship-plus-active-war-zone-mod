# Sims 4 Dictatorship Mod Prototype

This is a very simple prototype script mod for The Sims 4 that adds "dictatorship" themed cheat commands. Since it is a Python script mod, you need to follow specific steps to install it.

## Included Features (Cheat Commands)

Open the cheat console in-game by pressing `Ctrl + Shift + C` (or `Cmd + Shift + C` on Mac).

Once the console is open, type the following commands:

*   **`dictator.declare`**: The current Sim has been declared the Supreme Leader! (Text output)
*   **`dictator.tax <amount>`**: Collects taxes from the peasants. It will attempt to add the specified `amount` (default is 1000) to your current household's funds. e.g., `dictator.tax 5000`
*   **`dictator.arrest <first_name> <last_name>`**: Issues a warrant for the specified Sim. (Text output only - future feature)
*   **`dictator.propaganda`**: Broadcasts state propaganda. (Text output only - future feature)

## Installation Instructions

For Sims 4 script mods to work, the Python `.py` file **must** be compiled into a `.pyc` file and placed inside a `.zip` archive, or left as a `.ts4script` file (which is just a renamed `.zip`).

### Option 1: Quick Zip (if using uncompiled Python source)

Sometimes the game will read uncompiled `.py` files if they are just zipped, but it is highly recommended to compile them.

1.  Create a zip file containing `dictatorship_mod.py`. Let's call it `dictatorship_mod.ts4script` or `dictatorship_mod.zip`.
2.  Place the `.ts4script` or `.zip` file into your Sims 4 Mods folder:
    *   **Windows:** `Documents\Electronic Arts\The Sims 4\Mods`
    *   **Mac:** `Documents/Electronic Arts/The Sims 4/Mods`
3.  **Crucial Step:** Open The Sims 4, go to Game Options -> Other. Ensure that **both** "Enable Custom Content and Mods" AND "Script Mods Allowed" are checked.
4.  Restart the game.

### Option 2: Compiling to .pyc (Recommended for actual mods)

For a fully working mod, you generally need to decompile the Sims 4 base scripts, compile your `.py` against them, and then package the `.pyc` into a `.ts4script` file. There are many tutorials online (like Andrew's Sims 4 Studio tutorials) on how to set up a proper Sims 4 Python modding environment to compile `.pyc` files.

*Note: This repository currently only provides the `.py` source code file.*
