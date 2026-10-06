/* Small reusable component set over the classes in design.css. */
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react'
import './tokens.css'
import './design.css'

export type Tone = 'neutral' | 'gain' | 'loss' | 'warn'

const toneClass: Record<Tone, string> = {
  neutral: '',
  gain: 'text-gain',
  loss: 'text-loss',
  warn: 'text-warn',
}

function cx(...parts: Array<string | false | undefined>) {
  return parts.filter(Boolean).join(' ')
}

export function Panel(props: {
  title?: string
  actions?: ReactNode
  flush?: boolean
  children: ReactNode
}) {
  return (
    <section className="panel">
      {(props.title || props.actions) && (
        <header className="panel__header">
          <h2 className="panel__title">{props.title}</h2>
          {props.actions}
        </header>
      )}
      <div className={cx('panel__body', props.flush && 'panel__body--flush')}>{props.children}</div>
    </section>
  )
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'default' | 'primary' | 'toggle'
  size?: 'md' | 'sm'
  pressed?: boolean
}

export function Button({ variant = 'default', size = 'md', pressed, className, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      aria-pressed={variant === 'toggle' ? !!pressed : undefined}
      className={cx('btn', variant === 'primary' && 'btn--primary', variant === 'toggle' && 'btn--toggle',
        size === 'sm' && 'btn--sm', className)}
    />
  )
}

export function Checkbox({ label, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="check">
      <input type="checkbox" {...rest} />
      {label}
    </label>
  )
}

export function Badge({ tone = 'neutral', children, title }: {
  tone?: 'neutral' | 'warn' | 'accent'
  children: ReactNode
  title?: string
}) {
  return <span className={cx('badge', tone === 'warn' && 'badge--warn', tone === 'accent' && 'badge--accent')} title={title}>{children}</span>
}

export function Readout({ label, value, sub, tone = 'neutral' }: {
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: Tone
}) {
  return (
    <div className="readout">
      <span className="readout__label">{label}</span>
      <span className={cx('readout__value', 'mono', toneClass[tone])}>{value}</span>
      {sub && <span className="readout__sub">{sub}</span>}
    </div>
  )
}

export function Notice({ tone = 'warn', title, children }: {
  tone?: 'warn' | 'error'
  title?: string
  children?: ReactNode
}) {
  return (
    <div className={cx('notice', tone === 'warn' ? 'notice--warn' : 'notice--error')} role={tone === 'error' ? 'alert' : 'status'}>
      {title && <div className="notice__title">{title}</div>}
      {children}
    </div>
  )
}

export function Placeholder({ children }: { children: ReactNode }) {
  return <div className="placeholder">{children}</div>
}

/* Table primitives: numeric columns are right-aligned monospace. */
export function Table({ caption, children }: { caption: string; children: ReactNode }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  )
}

export function Th({ numeric, children, title }: { numeric?: boolean; children?: ReactNode; title?: string }) {
  return <th scope="col" className={cx(numeric && 'is-num')} title={title}>{children}</th>
}

export function Td({ numeric, tone = 'neutral', children, colSpan, note }: {
  numeric?: boolean
  tone?: Tone
  children?: ReactNode
  colSpan?: number
  note?: boolean
}) {
  return (
    <td colSpan={colSpan} className={cx(numeric && 'is-num num', note && 'is-note', toneClass[tone])}>
      {children}
    </td>
  )
}
