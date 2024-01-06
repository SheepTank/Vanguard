# Vanguard
Vanguard is a discord bot utilised to automatically manage bans across multiple discord servers.

## Commands

### Ban
`/banguard` - `/banguard member:discord.Member duration:str reason:str`
This bans a user, for a certain amount of time, for a reason. The reason gets added to the discord server audit log and processed by the bot on every server with an aggressive enforcement level.
#### Example
`/banguard member:sheeptank duration:7d reason:This isn't real!`
This would ban the user `sheeptank` for 7 days. 

### Unban
`/unbanguard` - `/unbanguard member:discord.Member`
This unbans a banned user.

#### Example
`/unbanguard member:sheeptank`

### Enforcement
`/enforcement` - `/enforcement enforce:["off", "on", "aggressive"]`
This sets the enforcement level of a discord guild. The different levels work as follows:
- off: This disables the enforcement entirely. If your audit channel is set, you will receive updates on whether a user with Vanguard history has joined.
- on: This enables the enforcement at a base level. This level prevents users with an active ban from joining your discord server. Vanguard will still warn you if someone with a past ban joins, and your audit channel is set up.
- aggressive: Vanguard will remove all users with an active ban within your server, even if it occurred in another server.

#### Example
`/enforcement enforce:aggressive`

### Ban Audit
`/banaudit` - `/banaudit`
The audit command returns a list of all users with history within the vanguard database.

#### Example
`/banaudit`

### Audit Channel
`/auditchannel` - `/auditchannel`
This sets the channel to be used for the audit notifications

#### Example
`/auditchannel`

### Sync
`/sync` - `/sync`
This ensures that the slash commands are synced with the discord server.
