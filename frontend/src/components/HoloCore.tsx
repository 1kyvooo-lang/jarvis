// The holographic JARVIS core: a rotating wireframe globe with orbiting particles.
// It reacts live to what he's doing: it breathes when idle, swells with your voice while
// listening, pulses with his voice while speaking, spins up while thinking or acting.
import { useEffect, useRef } from 'react'
import { levels } from '../levels'
import type { CoreState } from '../ui'

const COLORS: Record<CoreState, [number, number, number]> = {
  idle: [60, 231, 255], listening: [60, 231, 255], speaking: [120, 240, 255], thinking: [47, 123, 255],
  acting: [255, 181, 71], stopped: [255, 90, 106], offline: [86, 97, 109],
}
const SPIN: Record<CoreState, number> = {
  idle: 0.12, listening: 0.18, speaking: 0.22, thinking: 0.7, acting: 0.9, stopped: 0, offline: 0.04,
}

type P3 = [number, number, number]

function sphere(n: number): P3[] {
  const pts: P3[] = []
  const g = Math.PI * (3 - Math.sqrt(5))
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2, r = Math.sqrt(1 - y * y), t = g * i
    pts.push([Math.cos(t) * r, y, Math.sin(t) * r])
  }
  return pts
}

export default function HoloCore({ state, className = '' }: { state: CoreState; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const stateRef = useRef(state)
  stateRef.current = state

  useEffect(() => {
    const cv = ref.current!
    const ctx = cv.getContext('2d')!
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
    const pts = sphere(220)
    // neighbour links, computed once
    const links: [number, number][] = []
    for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) {
      const d = Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1], pts[i][2] - pts[j][2])
      if (d < 0.2) links.push([i, j])
    }
    const orbits = [
      { tilt: 0.35, speed: 0.5, r: 1.55, n: 3 }, { tilt: -0.6, speed: -0.35, r: 1.8, n: 2 }, { tilt: 1.2, speed: 0.28, r: 1.35, n: 2 },
    ]
    let w = 0, h = 0, dpr = 1
    const resize = () => {
      dpr = Math.min(devicePixelRatio || 1, 2)
      const r = cv.getBoundingClientRect()
      w = r.width; h = r.height
      cv.width = Math.max(1, w * dpr); cv.height = Math.max(1, h * dpr)
    }
    resize()
    const ro = new ResizeObserver(resize); ro.observe(cv)

    let angle = 0, spin = SPIN[state], amp = 0, col = [...COLORS[state]] as number[], last = performance.now(), raf = 0
    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now
      const st = stateRef.current
      const target = COLORS[st]
      for (let k = 0; k < 3; k++) col[k] += (target[k] - col[k]) * Math.min(1, dt * 4)
      spin += (SPIN[st] - spin) * Math.min(1, dt * 2)
      const live = st === 'listening' ? levels.mic : st === 'speaking' ? levels.out : 0
      amp += (live - amp) * Math.min(1, dt * 12)
      angle += spin * dt * (reduce ? 0.2 : 1)
      const breathe = st === 'idle' ? Math.sin(now / 900) * 0.015 : 0
      const c = (a: number) => `rgba(${col[0] | 0},${col[1] | 0},${col[2] | 0},${a})`

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      const cx = w / 2, cy = h / 2
      const R = Math.min(w, h) * 0.3 * (1 + breathe + amp * 0.12)

      // glow
      const g = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 2.1)
      g.addColorStop(0, c(0.22 + amp * 0.25)); g.addColorStop(0.45, c(0.07)); g.addColorStop(1, c(0))
      ctx.fillStyle = g; ctx.fillRect(0, 0, w, h)

      // base rings
      ctx.lineWidth = 1
      for (let i = 0; i < 4; i++) {
        ctx.strokeStyle = c(0.12 - i * 0.02)
        ctx.beginPath(); ctx.ellipse(cx, cy + R * 1.25, R * (0.6 + i * 0.28), R * (0.1 + i * 0.05), 0, 0, Math.PI * 2); ctx.stroke()
      }

      // rotate + project the globe
      const ca = Math.cos(angle), sa = Math.sin(angle), tilt = 0.32, ct = Math.cos(tilt), stt = Math.sin(tilt)
      const proj = pts.map(([x, y, z]) => {
        const x1 = x * ca + z * sa, z1 = -x * sa + z * ca
        const y2 = y * ct - z1 * stt, z2 = y * stt + z1 * ct
        const wob = st === 'speaking' || st === 'listening' ? 1 + amp * 0.08 * Math.sin(now / 90 + y * 6) : 1
        return [cx + x1 * R * wob, cy + y2 * R * wob, z2] as P3
      })
      for (const [i, j] of links) {
        const a = proj[i], b = proj[j], depth = (a[2] + b[2]) / 2
        ctx.strokeStyle = c(0.08 + (depth + 1) * 0.16)
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke()
      }
      for (const p of proj) {
        const s = 0.6 + (p[2] + 1) * 0.7
        ctx.fillStyle = c(0.25 + (p[2] + 1) * 0.35)
        ctx.fillRect(p[0] - s / 2, p[1] - s / 2, s, s)
      }
      // equator and meridian
      ctx.strokeStyle = c(0.5); ctx.lineWidth = 1.2
      ctx.beginPath(); ctx.ellipse(cx, cy, R, R * Math.abs(stt) + 2, 0, 0, Math.PI * 2); ctx.stroke()

      // orbits with particles
      orbits.forEach((o, k) => {
        ctx.save(); ctx.translate(cx, cy); ctx.rotate(o.tilt)
        ctx.strokeStyle = c(0.18); ctx.lineWidth = 1
        ctx.beginPath(); ctx.ellipse(0, 0, R * o.r, R * o.r * 0.32, 0, 0, Math.PI * 2); ctx.stroke()
        for (let i = 0; i < o.n; i++) {
          const t = now / 1000 * o.speed * (1 + spin) + (i / o.n) * Math.PI * 2 + k
          const px = Math.cos(t) * R * o.r, py = Math.sin(t) * R * o.r * 0.32
          const pg = ctx.createRadialGradient(px, py, 0, px, py, 9)
          pg.addColorStop(0, 'rgba(255,255,255,0.95)'); pg.addColorStop(0.3, c(0.8)); pg.addColorStop(1, c(0))
          ctx.fillStyle = pg; ctx.beginPath(); ctx.arc(px, py, 9, 0, Math.PI * 2); ctx.fill()
        }
        ctx.restore()
      })

      // voice ripples
      if (amp > 0.05) {
        for (let i = 0; i < 3; i++) {
          const ph = ((now / 700 + i / 3) % 1)
          ctx.strokeStyle = c((1 - ph) * amp * 0.6)
          ctx.lineWidth = 1.5
          ctx.beginPath(); ctx.arc(cx, cy, R * (1.05 + ph * 0.7), 0, Math.PI * 2); ctx.stroke()
        }
      }
      // outer tick ring
      ctx.save(); ctx.translate(cx, cy); ctx.rotate(-angle * 0.6)
      for (let i = 0; i < 90; i++) {
        const a = (i / 90) * Math.PI * 2, r1 = R * 1.95, r2 = r1 + (i % 5 === 0 ? 9 : 4)
        ctx.strokeStyle = c(i % 5 === 0 ? 0.45 : 0.18)
        ctx.beginPath(); ctx.moveTo(Math.cos(a) * r1, Math.sin(a) * r1); ctx.lineTo(Math.cos(a) * r2, Math.sin(a) * r2); ctx.stroke()
      }
      ctx.restore()
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => { cancelAnimationFrame(raf); ro.disconnect() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return <canvas ref={ref} className={`block w-full h-full ${className}`} aria-hidden />
}

/** A small live waveform bar that follows the mic or his voice. */
export function Wave({ active, bars = 28, className = '' }: { active: boolean; bars?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let raf = 0
    const loop = (t: number) => {
      const el = ref.current
      if (el) {
        const lvl = active ? Math.max(levels.mic, levels.out, 0.12) : 0.05
        Array.from(el.children).forEach((b, i) => {
          const v = 0.15 + Math.abs(Math.sin(t / 160 + i * 0.7)) * lvl * (0.6 + 0.4 * Math.sin(i * 1.3 + t / 400))
          ;(b as HTMLElement).style.transform = `scaleY(${Math.min(1, v * 1.6)})`
        })
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [active])
  return (
    <div ref={ref} className={`flex items-center gap-[3px] h-8 ${className}`} aria-hidden>
      {Array.from({ length: bars }).map((_, i) => <span key={i} className="w-[3px] h-full rounded-full bg-arc/80 origin-center transition-none" style={{ transform: 'scaleY(.15)' }} />)}
    </div>
  )
}
