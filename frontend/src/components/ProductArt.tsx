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
