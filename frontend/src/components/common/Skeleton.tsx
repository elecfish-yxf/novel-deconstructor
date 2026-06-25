/**
 * 骨架屏组件 - 用于各面板加载状态
 */

export function Skeleton({ width = "100%", height = "16px", style }: { width?: string; height?: string; style?: React.CSSProperties }) {
  return (
    <div
      className="skeleton-pulse"
      style={{
        width, height, borderRadius: 4, background: "#e2e8f0",
        animation: "skeleton-pulse 1.5s ease-in-out infinite",
        ...style,
      }}
    />
  );
}

export function SkeletonLine({ width = "80%" }) {
  return <Skeleton width={width} height="14px" style={{ marginBottom: 8 }} />;
}

export function SkeletonCard() {
  return (
    <div className="skeleton-card" style={{ padding: 12, marginBottom: 8, border: "1px solid #e2e8f0", borderRadius: 8 }}>
      <Skeleton width="60%" height="16px" style={{ marginBottom: 8 }} />
      <Skeleton width="40%" height="12px" style={{ marginBottom: 8 }} />
      <Skeleton width="90%" height="12px" />
      <Skeleton width="70%" height="12px" style={{ marginTop: 4 }} />
    </div>
  );
}

export function SkeletonPanel() {
  return (
    <div style={{ padding: 16 }}>
      <Skeleton width="50%" height="20px" style={{ marginBottom: 16 }} />
      <SkeletonLine width="90%" />
      <SkeletonLine width="70%" />
      <SkeletonLine width="80%" />
      <SkeletonLine width="60%" />
      <Skeleton width="40%" height="34px" style={{ marginTop: 12 }} />
      <SkeletonCard />
      <SkeletonCard />
      <SkeletonCard />
    </div>
  );
}

export function SkeletonInline({ count = 10 }: { count?: number }) {
  return (
    <div style={{ padding: 8 }}>
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonLine key={i} width={`${50 + Math.random() * 40}%`} />
      ))}
    </div>
  );
}
