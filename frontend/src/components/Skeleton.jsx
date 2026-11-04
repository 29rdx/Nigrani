import { Card } from './ui';

/** Grey placeholders that hold the page's shape while data loads, so nothing jumps when it arrives. */
export function Skel({ w = '100%', h = 14, style }) {
  return <i className="skel" style={{ width: w, height: h, ...style }} aria-hidden="true" />;
}

export function SkeletonTiles({ n = 6 }) {
  return (
    <div className="grid tiles" aria-hidden="true">
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="card skel-tile"><Skel w="40%" h={12} /><Skel w="55%" h={28} /><Skel h={26} /><Skel w="70%" h={10} /></div>
      ))}
    </div>
  );
}

export function SkeletonCard({ title = ' ', lines = 4 }) {
  return (
    <Card title={title}>
      <div className="stack" aria-hidden="true">{Array.from({ length: lines }, (_, i) => <Skel key={i} w={`${92 - i * 11}%`} h={14} />)}</div>
    </Card>
  );
}

export function SkeletonTable({ rows = 6 }) {
  return (
    <Card flush>
      <div className="list" aria-hidden="true">
        {Array.from({ length: rows }, (_, i) => <div key={i} className="row"><Skel w={60} h={20} /><Skel w="28%" h={14} /><Skel w="18%" h={14} style={{ marginLeft: 'auto' }} /></div>)}
      </div>
    </Card>
  );
}

/** What Suspense and the first load show: the shape of a typical page. */
export function PageSkeleton() {
  return (
    <div role="status" aria-label="Loading">
      <i className="skel skel-banner" aria-hidden="true" />
      <SkeletonTiles />
      <div className="grid g2" style={{ marginTop: 14 }}><SkeletonCard lines={5} /><SkeletonCard lines={5} /></div>
    </div>
  );
}

/** Rows inside a card that is already on screen. */
export function SkeletonRows({ rows = 4 }) {
  return (
    <div className="list" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => <div key={i} className="row"><Skel w={56} h={20} /><Skel w="30%" h={14} /><Skel w="16%" h={14} style={{ marginLeft: 'auto' }} /></div>)}
    </div>
  );
}
