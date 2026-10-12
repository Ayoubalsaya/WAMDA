import { useEffect, useState } from 'react'

// ثوانٍ متبقّية حتى `deadlineMs` (طابع زمني بالمللي ثانية)، تتحدّث كل ربع ثانية من الساعة لا من عدّاد تنازلي
// (المتصفح يُبطئ المؤقّتات في تبويب خلفي؛ الموعد النهائي هو المرجع). `0` حين لا موعد أو انتهى.
export function useCountdown(deadlineMs: number | null): number {
  const [, setTick] = useState(0) // يُعيد الرسم فقط؛ القيمة تُحسب من الساعة عند كل رسم
  useEffect(() => {
    if (deadlineMs === null) return
    const id = window.setInterval(() => setTick((t) => t + 1), 250)
    return () => window.clearInterval(id)
  }, [deadlineMs])
  return deadlineMs === null ? 0 : Math.max(0, Math.ceil((deadlineMs - Date.now()) / 1000))
}

// «12:07» — دقائق وثوانٍ بصفرٍ بادئ للثواني، لا عدد ثوانٍ خام
export function formatCountdown(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
