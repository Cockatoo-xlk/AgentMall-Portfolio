import { useId } from 'react'
import type { Category } from '../api/types'

interface Props {
  category: Category
  variant?: string
  className?: string
}

/** Original decorative product illustrations; no remote assets or brand imagery. */
export default function ProductArt({ category, variant = '', className = '' }: Props) {
  const id = useId().replace(/:/g, '')
  const color = [...variant].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 3
  const body = ['#c1cabc', '#c5c6b9', '#a9c3bd'][color]
  const dark = ['#35594f', '#4e5b54', '#376466'][color]
  return (
    <svg
      className={`product-art ${className}`}
      viewBox="0 0 480 340"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient
          id={`${id}-body`}
          x1="100"
          y1="80"
          x2="380"
          y2="290"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#edf0e4" />
          <stop offset="1" stopColor={body} />
        </linearGradient>
        <linearGradient
          id={`${id}-dark`}
          x1="160"
          y1="70"
          x2="320"
          y2="280"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor={dark} />
          <stop offset="1" stopColor="#173f3a" />
        </linearGradient>
        <linearGradient
          id={`${id}-key`}
          x1="0"
          y1="0"
          x2="0"
          y2="21"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#fffef4" />
          <stop offset="1" stopColor="#dedfd0" />
        </linearGradient>
        <filter id={`${id}-shadow`} x="-40%" y="-50%" width="180%" height="220%">
          <feGaussianBlur stdDeviation="11" />
        </filter>
      </defs>
      {(['smartphone', 'tablet'].includes(category)) && <g transform="rotate(-10 240 170)">
        <ellipse cx="245" cy="285" rx="105" ry="14" fill={dark} opacity=".1" />
        <rect x={category === 'tablet' ? 125 : 164} y="48" width={category === 'tablet' ? 230 : 150} height="242" rx="23" fill={dark} />
        <rect x={category === 'tablet' ? 135 : 174} y="59" width={category === 'tablet' ? 210 : 130} height="218" rx="16" fill={`url(#${id}-body)`} />
        <circle cx="240" cy="66" r="3" fill={dark} /><path d="M180 235 Q240 120 300 210" stroke="#f4f0d6" strokeWidth="20" />
      </g>}
      {(['laptop', 'monitor'].includes(category)) && <g transform="rotate(-5 240 170)">
        <rect x="75" y="62" width="330" height="205" rx="14" fill={dark} />
        <rect x="87" y="75" width="306" height="175" rx="7" fill={`url(#${id}-body)`} />
        <path d="M100 220 L180 130 L245 192 L310 110 L382 220Z" fill={body} /><circle cx="330" cy="111" r="18" fill="#e6e7b7" />
        {category === 'laptop' ? <path d="M75 267H405L437 290Q240 317 43 290Z" fill={body} stroke={dark} strokeWidth="3" /> : <><path d="M224 267H256L264 300H216Z" fill={dark} /><rect x="174" y="300" width="132" height="9" rx="4" fill={body} /></>}
      </g>}
      {category === 'camera' && <g transform="rotate(-9 240 170)">
        <path d="M152 119L168 92H231L249 119" fill={dark} /><rect x="82" y="117" width="316" height="168" rx="26" fill={`url(#${id}-body)`} stroke={dark} strokeWidth="4" />
        <rect x="101" y="131" width="35" height="137" rx="12" fill={dark} /><circle cx="249" cy="201" r="75" fill={dark} /><circle cx="249" cy="201" r="58" fill={body} /><circle cx="249" cy="201" r="39" fill="#173f3a" /><circle cx="235" cy="185" r="14" fill="#a9c3bd" opacity=".7" /><rect x="339" y="135" width="36" height="17" rx="3" fill="#f4f0d6" />
      </g>}
      {category === 'smartwatch' && <g transform="rotate(-15 240 170)">
        <rect x="201" y="20" width="78" height="300" rx="20" fill={body} /><rect x="172" y="96" width="136" height="152" rx="32" fill={dark} /><rect x="182" y="106" width="116" height="132" rx="24" fill={`url(#${id}-body)`} /><circle cx="240" cy="172" r="42" stroke={dark} strokeWidth="4" /><path d="M240 142V172L266 186" stroke={dark} strokeWidth="6" strokeLinecap="round" /><rect x="308" y="139" width="8" height="22" rx="4" fill={body} />
      </g>}
      {category === 'speaker' && <g transform="rotate(-8 240 170)">
        <rect x="147" y="40" width="186" height="260" rx="28" fill={`url(#${id}-body)`} stroke={dark} strokeWidth="4" /><circle cx="240" cy="110" r="35" fill={dark} /><circle cx="240" cy="213" r="64" fill={dark} /><circle cx="240" cy="213" r="45" fill={body} /><circle cx="240" cy="213" r="20" fill={dark} />
      </g>}
      {category === 'cycling' && <g transform="rotate(-12 240 170)">
        <path d="M89 211Q82 80 234 71Q385 77 397 205L315 231L139 239Z" fill={`url(#${id}-body)`} stroke={dark} strokeWidth="4" /><path d="M132 228L196 295L308 226M196 295L214 309" stroke={dark} strokeWidth="12" strokeLinejoin="round" />
        {[159,212,265,318].map(x => <path key={x} d={`M${x} 112L${x+19} 172`} stroke={dark} strokeWidth="15" strokeLinecap="round" />)}<path d="M97 213Q239 246 390 203" stroke={dark} strokeWidth="10" />
      </g>}
      {category === 'fitness' && <g transform="rotate(-23 240 170)">
        <rect x="118" y="154" width="242" height="38" rx="12" fill={body} stroke={dark} strokeWidth="4" />
        {[101,321].map(x => <g key={x}><rect x={x} y="101" width="58" height="147" rx="16" fill={dark} /><rect x={x+11} y="111" width="36" height="127" rx="12" fill={`url(#${id}-body)`} /></g>)}
      </g>}
      {category === 'home_appliance' && <g transform="rotate(-5 240 170)">
        <rect x="127" y="49" width="191" height="245" rx="24" fill={`url(#${id}-body)`} stroke={dark} strokeWidth="4" /><rect x="145" y="86" width="151" height="56" rx="8" fill={dark} /><circle cx="266" cy="111" r="12" fill={body} /><rect x="167" y="166" width="134" height="97" rx="10" fill={dark} /><path d="M179 190H246V241Q211 254 179 241Z" fill="#f8f4e7" /><path d="M246 198H265Q286 218 246 230" stroke="#f8f4e7" strokeWidth="8" /><path d="M201 160V178M222 160V178" stroke={dark} strokeWidth="5" /><rect x="111" y="282" width="224" height="18" rx="8" fill={dark} />
      </g>}
      {category === 'keyboard' && (
        <g transform="translate(5 1) rotate(-13 240 170)">
          <ellipse
            cx="244"
            cy="242"
            rx="173"
            ry="25"
            fill="#315148"
            opacity=".16"
            filter={`url(#${id}-shadow)`}
          />
          <rect x="54" y="106" width="374" height="151" rx="19" fill="#879b90" />
          <rect
            x="54"
            y="96"
            width="374"
            height="150"
            rx="18"
            fill={`url(#${id}-body)`}
            stroke="#9dac9c"
          />
          <rect x="65" y="108" width="352" height="123" rx="10" fill="#9aaa98" opacity=".7" />
          {[0, 1, 2, 3].map((row) =>
            Array.from({ length: 13 }, (_, col) => {
              const accent = (row === 0 && col === 0) || (row === 2 && col === 12)
              const fill = accent ? dark : row === 0 && col === 12 ? '#d8e785' : `url(#${id}-key)`
              return (
                <g
                  key={`${row}-${col}`}
                  transform={`translate(${71 + col * 26.1} ${113 + row * 23.1})`}
                >
                  <rect
                    y="2"
                    width="23"
                    height="20"
                    rx="3.5"
                    fill={accent ? '#1d3b34' : '#b8bdab'}
                  />
                  <rect
                    width="23"
                    height="18"
                    rx="3.5"
                    fill={fill}
                    stroke={accent ? dark : '#f7f8ed'}
                    strokeWidth=".7"
                  />
                  {row > 0 && col > 0 && col < 11 && (
                    <path
                      d="M9 6h4M9 8h3"
                      stroke={accent ? '#d7e6db' : '#748173'}
                      strokeWidth=".7"
                      opacity=".7"
                    />
                  )}
                </g>
              )
            }),
          )}
          {[
            { x: 71, w: 29 },
            { x: 103, w: 29 },
            { x: 135, w: 29 },
            { x: 167, w: 134 },
            { x: 304, w: 29 },
            { x: 336, w: 29 },
            { x: 368, w: 40 },
          ].map((key, index) => (
            <g key={key.x} transform={`translate(${key.x} 207)`}>
              <rect y="2" width={key.w} height="18" rx="3.5" fill="#aeb7a6" />
              <rect
                width={key.w}
                height="17"
                rx="3.5"
                fill={index === 6 ? '#d6e385' : '#eef0df'}
                stroke="#f6f7ed"
                strokeWidth=".7"
              />
            </g>
          ))}
          <circle cx="401" cy="102" r="1.5" fill="#d9f193" />
        </g>
      )}
      {category === 'mouse' && (
        <g transform="rotate(-17 240 170)">
          <ellipse
            cx="245"
            cy="285"
            rx="78"
            ry="17"
            fill="#315148"
            opacity=".17"
            filter={`url(#${id}-shadow)`}
          />
          <path
            d="M244 55c-48 0-74 38-77 94l-5 74c-2 39 29 64 80 64s79-25 77-64l-5-74c-4-57-24-94-70-94Z"
            fill="#8ca397"
          />
          <path
            d="M240 49c-48 0-73 38-77 94l-5 72c-2 39 29 65 80 65s81-26 79-65l-5-72c-4-56-26-94-72-94Z"
            fill={`url(#${id}-body)`}
            stroke="#a0afa0"
          />
          <path d="M240 51v108M165 159c43 15 97 15 149 0" stroke="#8da292" strokeWidth="1.5" />
          <rect x="231" y="83" width="18" height="41" rx="9" fill="#547165" />
          <rect x="234" y="87" width="12" height="29" rx="6" fill="#d5e38d" />
          {[92, 97, 102, 107].map((y) => (
            <path key={y} d={`M236 ${y}h8`} stroke="#9caa6c" strokeWidth=".8" />
          ))}
          <path
            d="M175 191c-3 19-2 35 3 47"
            stroke="#f2f4e8"
            strokeWidth="4"
            strokeLinecap="round"
            opacity=".8"
          />
          <circle cx="239" cy="240" r="4" fill={dark} opacity=".5" />
        </g>
      )}
      {category === 'headphones' && (
        <g transform="rotate(10 240 170)">
          <ellipse
            cx="243"
            cy="284"
            rx="103"
            ry="17"
            fill="#315148"
            opacity=".16"
            filter={`url(#${id}-shadow)`}
          />
          <path
            d="M143 193v-42c0-64 37-105 97-105s97 41 97 105v42"
            stroke="#9cae9c"
            strokeWidth="28"
            strokeLinecap="round"
          />
          <path
            d="M143 184v-36c0-59 38-96 97-96s97 37 97 96v36"
            stroke={`url(#${id}-body)`}
            strokeWidth="21"
            strokeLinecap="round"
          />
          <path
            d="M167 96c17-22 41-32 73-32s56 10 73 32"
            stroke={dark}
            strokeWidth="13"
            strokeLinecap="round"
          />
          <path d="M143 162v55M337 162v55" stroke="#6d8778" strokeWidth="10" />
          <g transform="rotate(-13 152 222)">
            <rect x="117" y="167" width="66" height="112" rx="30" fill="#8ba391" />
            <rect
              x="124"
              y="164"
              width="62"
              height="109"
              rx="29"
              fill={`url(#${id}-body)`}
              stroke="#a1b29f"
            />
            <rect x="159" y="173" width="29" height="93" rx="14.5" fill={`url(#${id}-dark)`} />
            <path d="M135 188v58" stroke="#f5f6e9" strokeWidth="4" strokeLinecap="round" />
          </g>
          <g transform="rotate(13 328 222)">
            <rect x="296" y="167" width="66" height="112" rx="30" fill="#8ba391" />
            <rect
              x="294"
              y="164"
              width="62"
              height="109"
              rx="29"
              fill={`url(#${id}-body)`}
              stroke="#a1b29f"
            />
            <rect x="291" y="173" width="29" height="93" rx="14.5" fill={`url(#${id}-dark)`} />
            <path d="M344 189v55" stroke="#f5f6e9" strokeWidth="4" strokeLinecap="round" />
            <circle cx="338" cy="253" r="3" fill="#d1e280" />
          </g>
        </g>
      )}
    </svg>
  )
}
