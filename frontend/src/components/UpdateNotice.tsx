import { useEffect, useState } from 'react';
export function UpdateNotice() {
  const [version, setVersion] = useState('');
  const [url, setUrl] = useState('https://github.com/noguhiro2002/FlintEye/releases');
  useEffect(() => {
    let active = true;
    void fetch('/api/v1/updates', { credentials: 'include' }).then(async response => {
      if (!response.ok) return;
      const release = await response.json();
      if (active && release.available) {
        setVersion(release.version);
        if (typeof release.url === 'string' && /^https:\/\/github\.com\/noguhiro2002\/FlintEye\/releases\/tag\/v?[0-9]+\.[0-9]+\.[0-9]+(?:-preview\.[1-9][0-9]*)?$/.test(release.url)) setUrl(release.url);
      }
    }).catch(() => undefined);
    return () => { active = false; };
  }, []);
  return version ? <div className="panel-note" role="status">
    FlintEye {version} is available. Stop monitoring before updating.{' '}
    <a href={url} target="_blank" rel="noreferrer">View release</a>
  </div> : null;
}
