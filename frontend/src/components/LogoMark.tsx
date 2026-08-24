/** علامة الشعار — ومضة (⚡) بيضاء، تُستخدم داخل مربع بالتدرج الرسمي في
 * شاشة الدخول وترويسات المطبوعات (و-١). SVG مضمّن، بلا اعتماد خارجي. */
export function LogoMark({ size = 36, color = '#fff' }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M13.2 2 4.8 13.4h5.6L10 22l9-11.6h-5.9L13.2 2Z"
        fill={color}
      />
    </svg>
  )
}
