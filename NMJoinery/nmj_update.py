"""
Updates: a while after Fusion starts, look on GitHub for a newer release of this add-in and,
if there is one, ask once:
    Yes    = install it now (download the zip, replace the add-in's files, keep your own files);
             restart Fusion to use it
    No     = skip this version (don't ask again until the next one)
    Cancel = not now (ask again next time Fusion starts)

- Reads the public release list and downloads the release zip only; nothing about you or your
  designs is sent. No GitHub account needed. No network or GitHub down -> nothing happens.
- Installs itself only when the add-in sits in Fusion's own add-in folder (.../API/AddIns/<name>,
  where the installer puts it). Anywhere else (e.g. a working copy added with +) it only offers to
  open the download page, so a source folder is never overwritten.
- Your own files (presets, last settings, update_seen.json, the log) are not in the zip and stay.

The same file is in every NM add-in under its own name (nmj_update.py, ru_update.py), so two add-ins
never share one copy. Releases are tagged <addin name in lower case>-v<version>, e.g. nmjoinery-v0.7.0,
with the asset <name>-<version>.zip holding the folder <name>/.
"""
import io, json, os, re, shutil, tempfile, threading, time, urllib.request, webbrowser, zipfile
import adsk.core

REPO = 'nvdberg/fusion-addins'
API = 'https://api.github.com/repos/%s/releases?per_page=50' % REPO
DELAY = 20          # seconds after start-up, so Fusion is done loading
_state = {}         # name -> {'handler', 'event', 'stop'}
_UA = {'User-Agent': 'fusion-addin-update-check'}
_zips = {}          # name -> the downloaded release zip (fetched in the background, so Yes doesn't freeze Fusion)


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


def can_self_update(folder, name):
    """Only a copy in Fusion's own add-in folder (.../API/AddIns/<name>) replaces itself."""
    p = os.path.realpath(folder)
    up = os.path.dirname(p)
    return (os.path.basename(p) == name and os.path.basename(up) == 'AddIns'
            and os.path.basename(os.path.dirname(up)) == 'API' and not os.path.exists(os.path.join(p, '.git')))


def newest(name):
    """(version, page url, zip url or '') of the newest published release of this add-in, or None."""
    req = urllib.request.Request(API, headers=dict(_UA, Accept='application/vnd.github+json'))
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
            zip_url = ''
            for a in r.get('assets') or []:
                if a.get('name') == '%s-%s.zip' % (name, v):
                    zip_url = a.get('browser_download_url', '')
            best = (v, r.get('html_url') or 'https://github.com/%s/releases' % REPO, zip_url)
    return best


def download(zip_url):
    req = urllib.request.Request(zip_url, headers=_UA)
    with urllib.request.urlopen(req, timeout=60) as f:
        return f.read()


def install(name, folder, zip_url, want, data=None):
    """Copy the release zip's <name>/ files over this add-in's folder (downloads the zip unless data is given).
    Files that are not in the zip (presets, last settings, log) are left alone. Returns the new version.
    All new files are written next to the old ones first (.nmnew) and only then swapped in, so a failure
    (disk full, a locked file) leaves the add-in as it was."""
    if data is None:
        data = download(zip_url)
    zf = zipfile.ZipFile(io.BytesIO(data))
    pre = name + '/'
    members = [m for m in zf.namelist() if m.startswith(pre) and not m.endswith('/')]
    for m in members:                                   # nothing outside <name>/, no ../ tricks
        if '..' in m.split('/') or m.startswith('/') or '\\' in m:
            raise ValueError('unexpected path in zip: %s' % m)
    if pre + name + '.manifest' not in members:
        raise ValueError('no %s.manifest in the zip' % name)
    got = json.loads(zf.read(pre + name + '.manifest').decode('utf-8')).get('version', '')
    if _ver(got) != _ver(want):
        raise ValueError('zip holds version %s, expected %s' % (got, want))
    tmp = tempfile.mkdtemp(prefix='nm-update-')
    try:                                                # unpack everything first, then swap file by file
        for m in members:
            rel = m[len(pre):]
            if '__pycache__' in rel.split('/') or rel.endswith('.DS_Store'):
                continue
            dst = os.path.join(tmp, *rel.split('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as out:
                out.write(zf.read(m))
        staged = []
        try:
            for root, _dirs, files in os.walk(tmp):
                for fn in files:
                    src = os.path.join(root, fn)
                    dst = os.path.join(folder, os.path.relpath(src, tmp))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copyfile(src, dst + '.nmnew')
                    staged.append(dst)
        except Exception:
            for dst in staged:
                try:
                    os.remove(dst + '.nmnew')
                except OSError:
                    pass
            raise
        for dst in staged:
            os.replace(dst + '.nmnew', dst)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return got


class _Show(adsk.core.CustomEventHandler):
    def __init__(self, name, folder, log):
        super().__init__()
        self.name, self.folder, self.log = name, folder, log

    def _skip(self, v):
        with open(_seen_path(self.folder), 'w', encoding='utf-8') as f:
            json.dump({'skip': v}, f)

    def notify(self, args):
        try:
            d = json.loads(args.additionalInfo)
            ui = adsk.core.Application.get().userInterface
            title = '%s update' % self.name
            B = adsk.core.MessageBoxButtonTypes
            if d.get('zip') and can_self_update(self.folder, self.name):
                r = ui.messageBox('%s %s is out (you have %s).\n\nInstall it now?\n\n'
                                  'Yes = download and install it (takes a few seconds; your presets and '
                                  'last settings are kept). Restart Fusion afterwards to use it.\n'
                                  'No = skip this version.\nCancel = ask me next time.\n\n'
                                  'What changed: %s' % (self.name, d['v'], d['have'], d['url']),
                                  title, B.YesNoCancelButtonType)
                if r == adsk.core.DialogResults.DialogYes:
                    try:
                        got = install(self.name, self.folder, d['zip'], d['v'], _zips.pop(self.name, None))
                        self.log('updated to %s' % got)
                        ui.messageBox('%s %s is installed.\n\nRestart Fusion to use it '
                                      '(until then the old version keeps running).' % (self.name, got), title)
                    except Exception as e:
                        self.log('update install failed: %s' % e)
                        if ui.messageBox('The update could not be installed:\n%s\n\nOpen the download page '
                                         'instead?' % e, title, B.YesNoButtonType) == adsk.core.DialogResults.DialogYes:
                            webbrowser.open(d['url'])
                elif r == adsk.core.DialogResults.DialogNo:
                    self._skip(d['v'])
                return
            r = ui.messageBox('%s %s is out (you have %s).\n\nOpen the download page?\n\n'
                              'It has the zip and what changed. To update, run the installer from the zip '
                              '(or replace the add-in folder with the new one).\n'
                              '"No" = don\'t ask again for this version.'
                              % (self.name, d['v'], d['have']), title, B.YesNoButtonType)
            if r == adsk.core.DialogResults.DialogYes:
                webbrowser.open(d['url'])
            else:
                self._skip(d['v'])
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
        v, url, zip_url = got
        if _ver(v) > _ver(have) and v != _seen(folder) and not stop.is_set():
            if zip_url and can_self_update(folder, name):
                try:
                    _zips[name] = download(zip_url)
                except Exception as e:
                    log('update zip not fetched yet: %s' % e)     # Yes downloads it then
            if stop.is_set():
                return
            adsk.core.Application.get().fireCustomEvent(
                event_id, json.dumps({'v': v, 'have': have, 'url': url, 'zip': zip_url}))
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
