![version](https://img.shields.io/badge/version-19%2B-5682DF)
![platform](https://img.shields.io/static/v1?label=platform&message=mac-intel%20|%20mac-arm&color=blue)
[![license](https://img.shields.io/github/license/miyako/4d-plugin-mount)](LICENSE)
![downloads](https://img.shields.io/github/downloads/miyako/4d-plugin-mount/total)

# 4d-plugin-mount

Volume mount notification for Mac. The plugin listens to the `NSWorkspace` volume notifications (did mount, will unmount, did unmount, did rename) and calls a 4D project method of your choice with a JSON description of each event. It can also mount and unmount disks through the macOS Disk Arbitration framework. Event data arrives as `Text` (JSON); [Unmount](#unmount) returns the disk's BSD name as `Text`.

| Command | Returns | Purpose |
|---|---|---|
| [Mount WATCH](#mount-watch) | — | Start, change or stop the volume event callback |
| [Unmount](#unmount) | `Text` | Request a forced unmount of a volume, given its path |
| [Mount](#mount) | — | Request a mount of a disk, given its BSD name |

**Platforms:** macOS only (Intel and Apple silicon; macOS 11.5 or later for builds from 1.3.0).

---

## Requirements & platform notes

- **macOS only.** The Windows64 binary in the bundle is the empty Plugin Wizard stub, and the source has no Windows implementation, so the commands do nothing on Windows (inferred from the stub, not tested).
- Requires 4D v19 or later (as stated by the version badge).
- **Failure is silent.** None of the commands raises a 4D error. [Mount](#mount) and [Unmount](#unmount) only *request* the operation from Disk Arbitration and return before it completes; the plugin never reports whether it succeeded.
- **Unmounting is forced.** [Unmount](#unmount) uses `kDADiskUnmountOptionForce`: the volume is unmounted even if applications have files open on it.
- The commands are not thread-safe (`"threadSafe": false` in the manifest): call them from cooperative processes only.
- Paths are **HFS paths** (`Macintosh HD:Volumes:MyDisk:`), the native 4D path style on macOS, not POSIX paths.

---

## Mount WATCH

### Syntax

```
Mount WATCH ( method )
```

| Parameter | Type | Description |
|---|---|---|
| `method` | Text | Name of the project method to call for each volume event. Pass `""` to stop watching. |
| Result | — | None |

### Description

When `method` is not empty, the plugin starts observing volume notifications and starts a background 4D process named `$mount`. For each event, the plugin builds a JSON object (see [Event object](#event-object)) and queues it; the `$mount` process calls `method` once per queued event, in order, with the JSON text as `$1`.

- `method` is looked up as a project method by name. If no such method exists, the plugin hands the name and the JSON text to 4D's `EXECUTE METHOD` (command 1007) instead, so the resulting 4D error should appear in the `$mount` process (inferred, not tested).
- Calling `Mount WATCH` again with another name while watching changes the callback method; the same `$mount` process keeps running.
- `Mount WATCH ("")` stops the `$mount` process and removes the notification observers. Events still queued at that moment may be dropped.
- The `$mount` process checks for new events about once a second (it sleeps 59 ticks between checks), so the callback can run up to about a second after the event.
- Watching stops automatically when 4D quits (when the `$xx` exit process closes).
- Events come from macOS, so they only report volumes on the machine where the plugin runs (on 4D Server, the server machine; inferred, not tested).

#### Event object

`$1` is JSON text with these properties:

| Property | Type | Description |
|---|---|---|
| `type` | Longint | One of the **Mount Event Types** constants (below). |
| `volumePath` | Text | HFS path of the volume. |
| `volumeURL` | Text | `file://` URL of the volume. |
| `volumeLocalizedName` | Text | Volume name as the Finder displays it. |
| `devicePath` | Text | Mount point as reported by `NSWorkspace` (`NSDevicePath`). Mount and unmount events only. |
| `volumeOldLocalizedName` | Text | Previous name. Rename event only. |
| `volumeOldPath` | Text | Previous HFS path. Rename event only. |
| `volumeOldURL` | Text | Previous `file://` URL. Rename event only. |

A value macOS does not provide is `""` (since the 1.3.0 review fixes; before them, a missing value could crash 4D).

| Constant | Value |
|---|---|
| `Volume did mount event` | 1 |
| `Volume will unmount event` | 2 |
| `Volume did unmount event` | 3 |
| `Volume did rename event` | 4 |

### Example

From the plugin's own test method (`TEST.4dm`):

```4d
Mount WATCH ("mount_watch")
```

The callback, from the plugin's own test method (`mount_watch.4dm`):

```4d
C_TEXT:C284($1)

C_OBJECT:C1216($json)

$json:=JSON Parse:C1218($1;Is object:K8:27)

Case of 
	: ($json.type=Volume did mount event)
		
	: ($json.type=Volume did rename event)
		
	: ($json.type=Volume did unmount event)
		
	: ($json.type=Volume will unmount event)
		
End case 
```

Stop watching:

```4d
Mount WATCH ("")
```

---

## Unmount

### Syntax

```
bsdName := Unmount ( volumePath )
```

| Parameter | Type | Description |
|---|---|---|
| `volumePath` | Text | HFS path of the mounted volume. |
| Result | Text | BSD name of the volume's disk (for example `disk4s1`), or `""`. |

### Description

Looks up the disk behind `volumePath`, returns its BSD name, and asks Disk Arbitration to unmount it with the force option. The command returns immediately: the result tells you which disk was asked to unmount, not that the unmount succeeded. Keep the BSD name to [Mount](#mount) the disk again later.

The result is `""` when the path does not resolve to a disk, or when the volume has no BSD device, such as a network share (since the 1.3.0 review fixes; before them, that case could crash 4D).

### Example

From the plugin's own test method (`TEST_1.4dm`):

```4d
  //$bsdname:=Unmount ("Volumes:SUMMITPCLAS")
$bsdname:=Unmount ("Macintosh HD:Volumes:SUMMITPCLAS")
Mount ($bsdname)
```

Act only if a disk was found:

```4d
C_TEXT($bsdname)
$bsdname:=Unmount ("Macintosh HD:Volumes:MyDisk:")
If ($bsdname#"")
	ALERT("Unmount requested for "+$bsdname)
End if 
```

---

## Mount

### Syntax

```
Mount ( bsdName )
```

| Parameter | Type | Description |
|---|---|---|
| `bsdName` | Text | BSD name of the disk to mount, as returned by [Unmount](#unmount) (for example `disk4s1`). |
| Result | — | None |

### Description

Asks Disk Arbitration to mount the disk at its default mount point. The command returns immediately and reports nothing; an unknown BSD name is ignored. Use [Mount WATCH](#mount-watch) to learn when the volume actually appears (`Volume did mount event`).

### Example

From the plugin's own test method (`TEST_1.4dm`), after [Unmount](#unmount):

```4d
Mount ($bsdname)
```

---

## Error handling & troubleshooting

- **No 4D error, ever.** All three commands fail silently. Check the [Unmount](#unmount) result for `""`, and use the [Mount WATCH](#mount-watch) events to confirm that a mount or unmount took place.
- **Unmount is forced.** Open files on the volume do not prevent the unmount; save and close them first.
- **Callback not called.** Check the method name passed to [Mount WATCH](#mount-watch). Events arrive up to about a second late.
- **Restarting right after stopping.** If you call `Mount WATCH ("")` and then `Mount WATCH ("method")` before the `$mount` process has ended, watching may silently not restart. Call [Mount WATCH](#mount-watch) with the new method name directly instead of stopping first.
- **Paths are HFS paths.** Pass `Macintosh HD:Volumes:MyDisk:`, not `/Volumes/MyDisk`.
- **Windows.** The bundled Windows binary is an empty stub; nothing happens there.

---

## Quick reference

```4d
Mount WATCH ("mount_watch")  // $1 = JSON text; $json.type = Volume did mount event, ...
$bsdname:=Unmount ("Macintosh HD:Volumes:MyDisk:")  // forced, asynchronous
Mount ($bsdname)  // asynchronous
Mount WATCH ("")  // stop
```

---

## Releases

[Releases](https://github.com/miyako/4d-plugin-mount/releases)

Maintainers: [manual Bump and Build workflows](.github/README.md).

Older documentation: [miyako.github.io](https://miyako.github.io/2019/10/02/4d-plugin-mount)
