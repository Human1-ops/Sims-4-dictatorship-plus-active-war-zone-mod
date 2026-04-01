# The Sims 4 Dictatorship Mod

This is a pure Python script mod for The Sims 4 that allows you to play out a Dictatorship scenario, complete with military deployments, custom rules, and sham elections!

## Features

- **Become the Dictator**: Claim power for your active Sim and establish a regime.
- **Rules and Punishments**: Set rules (like "no_dancing") and let the military enforce them. Rulebreakers face physical fights and potential jail time!
- **Taxes**: Demand taxes directly into your household funds (at the cost of your reputation).
- **The Military & Draft**: Draft sims into your army. Deployed sims will travel to offscreen "war zones" or training zones.
- **Elections via Mailboxes & NAP Boards**: Click on any Mailbox or Community Board to hold a "Vote". The Dictator will run against a Celebrity Politician. Voter preference is influenced by their Eco Footprint and your reputation!

## Installation

1. Do **NOT** extract or unzip the `.ts4script` file!
2. Place `dictatorship_mod.ts4script` directly into your `Documents/Electronic Arts/The Sims 4/Mods` folder.
3. Make sure "Script Mods Allowed" is checked in your Game Options.

## Commands

Open the cheat console (`Ctrl+Shift+C`) and use these commands:

- `dictator.make_dictator [FirstName] [LastName]`: Appoints the target Sim as the Dictator.
- `dictator.die`: Forces the current Dictator to die and triggers succession (to a child).
- `dictator.check_reputation`: Prints the Dictator's current reputation score and title.
- `dictator.set_rule [rule_name]`: Adds a new rule (e.g., `dictator.set_rule no_dancing`).
- `dictator.remove_rule [rule_name]`: Revokes an active rule.
- `dictator.break_rule [rule_name] [FirstName] [LastName]`: Simulates the target Sim breaking a rule. The military will fight them!
- `dictator.arrest [FirstName] [LastName]`: Instantly arrests the target and despawns them for 3 Sim days.
- `dictator.banish [FirstName] [LastName]`: Banishes (destroys) the target Sim permanently.
- `dictator.demand_taxes [amount]`: Adds Simoleons to your household funds, lowering your reputation.
- `dictator.hold_election`: Manually triggers an election (You can also do this by clicking the "Vote" interaction on mailboxes).
- `dictator.declare_war`: Manually declares a new war zone in the world.
- `dictator.draft_sim [FirstName] [LastName]`: Drafts a Sim to fight in an active war zone.
- `dictator.deploy_training [FirstName] [LastName]`: Sends a Sim to a random world for a training deployment (they will do pushups and jog).
- `dictator.trigger_scandal`: Forces a political scandal, severely lowering reputation.
- `dictator.travel_to_war`: Forces the Dictator to travel to an active war zone to observe the fighting.