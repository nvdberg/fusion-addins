"""
Update notice: a while after Fusion starts, look on GitHub for a newer release of this add-in and,
if there is one, ask once whether to open its download page.

- Reads the public release list only; nothing about you or your designs is sent.
- No GitHub account needed. No network or GitHub down -> nothing happens.
- "No" = don't ask again for that version (kept in update_seen.json in the add-in folder).
- Never downloads or changes anything by itself.

The same file is in every NM add-in under its own name (nmj_update.py, ru_update.py), so two add-ins
never share one copy. Releases are tagged <addin name in lower case>-v<version>, e.g. nmjoinery-v0.7.0.
"""
import json, os, re, threading, time, urllib.request, webbrowser
import adsk.core

REPO = 'nvdberg/fusion-addins'
API = 'https://api.github.com/repos/%s/releases?per_page=50' % REPO
DELAY = 20          # seconds after start-up, so Fusion is done loading
_state = {}         # name -> {'handler', 'event', 'stop'}


def _ver(s):
    return tuple(int(n) for n in re.findall(r'\d+', s or '')[:3])


def _installed(folder, name):
    try:
        with open(os.path.join(folder, name + '.manifest'), encoding='utf-8') as f:
            return json.load(f).get('version', '0')
    except Exception:
        return '0'


def _seen_path(folder):
    return os.path.join(folder, 'update_seen.json')


def _seen(folder):
    try:
        with open(_seen_path(folder), encoding='utf-8') as f:
            return json.load(f).get('skip', '')
    except Exception:
        return ''


def newest(name):
    """(version, page url) of the newest published release of this add-in, or None."""
    req = urllib.request.Request(API, headers={'User-Agent': 'fusion-addin-update-check',
                                               'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=10) as f:
        rel = json.load(f)
    pre = name.lower() + '-v'
    best = None
    for r in rel:
        tag = r.get('tag_name', '')
        if r.get('draft') or r.get('prerelease') or not tag.lower().startswith(pre):
            continue
        v = tag[len(pre):]
        if best is None or _ver(v) > _ver(best[0]):
            best = (v, r.get('html_url') or 'https://github.com/%s/releases' % REPO)
    return best


class _Show(adsk.core.CustomEventHandler):
    def __init__(self, name, folder, log):
        super().__init__()
        self.name, self.folder, self.log = name, folder, log

    def notify(self, args):
        try:
            d = json.loads(args.additionalInfo)
            ui = adsk.core.Application.get().userInterface
            r = ui.messageBox('%s %s is out (you have %s).\n\nOpen the download page?\n\n'
                              'It has the zip and what changed. Install it the same way as before: '
                              'stop the add-in, replace its folder with the new one, run it again.\n'
                              '"No" = don\'t ask again for this version.'
                              % (self.name, d['v'], d['have']), '%s update' % self.name,
                              adsk.core.MessageBoxButtonTypes.YesNoButtonType)
            if r == adsk.core.DialogResults.DialogYes:
                webbrowser.open(d['url'])
            else:
                with open(_seen_path(self.folder), 'w', encoding='utf-8') as f:
                    json.dump({'skip': d['v']}, f)
        except Exception as e:
            self.log('update notice failed: %s' % e)


def _check(name, folder, log, event_id, stop):
    time.sleep(DELAY)
    if stop.is_set():
        return
    try:
        have = _installed(folder, name)
        got = newest(name)
        if not got:
            return
        v, url = got
        if _ver(v) > _ver(have) and v != _seen(folder) and not stop.is_set():
            adsk.core.Application.get().fireCustomEvent(event_id, json.dumps({'v': v, 'have': have, 'url': url}))
        else:
            log('up to date (%s, newest on GitHub %s)' % (have, v))
    except Exception as e:
        log('update check skipped: %s' % e)


def start(name, folder, log=lambda m: None):
    """Call from the add-in's run(). Never raises."""
    try:
        stop_(name)
        app = adsk.core.Application.get()
        event_id = 'nmUpdate_' + name
        try:
            app.unregisterCustomEvent(event_id)
        except Exception:
            pass
        ev = app.registerCustomEvent(event_id)
        h = _Show(name, folder, log)
        ev.add(h)
        stop = threading.Event()
        _state[name] = {'handler': h, 'event': event_id, 'stop': stop}
        threading.Thread(target=_check, args=(name, folder, log, event_id, stop), daemon=True).start()
    except Exception as e:
        log('update check not started: %s' % e)


def stop_(name):
    """Call from the add-in's stop()."""
    s = _state.pop(name, None)
    if not s:
        return
    s['stop'].set()
    try:
        adsk.core.Application.get().unregisterCustomEvent(s['event'])
    except Exception:
        pass
