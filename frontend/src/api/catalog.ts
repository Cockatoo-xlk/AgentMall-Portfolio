import type { Category, Product } from './types'

export const categoryLabels = {
  keyboard: '键盘', mouse: '鼠标', headphones: '耳机', smartphone: '手机', laptop: '笔记本电脑',
  tablet: '平板电脑', monitor: '显示器', camera: '摄影器材', smartwatch: '智能手表',
  speaker: '音箱', cycling: '骑行装备', fitness: '健身器材', home_appliance: '生活家电',
} satisfies Record<Category, string>

export const attributeLabels: Record<string, string> = {
  switch: '轴体', connection: '连接方式', connection_capabilities: '连接能力', size: '规格', noise: '噪声标签',
  processor_tier: '处理器等级', memory: '内存', storage: '存储', screen_size: '屏幕尺寸',
  screen_inches: '屏幕英寸', battery_grade: '续航等级', imaging: '影像定位', usage: '适用场景',
  weight: '重量', resolution: '分辨率', refresh_rate: '刷新率', panel: '面板', ports: '接口',
  camera_type: '相机类型', sensor_class: '传感器类别', video: '视频规格', features: '功能',
  speaker_type: '音箱类型', power: '功率', equipment_type: '器材类型', material: '材质',
  resistance: '重量 / 阻力', appliance_type: '家电类型', capacity: '容量', sensitivity: '灵敏度',
  form: '佩戴方式', driver: '单元规格',
}
const summaryKeys: Record<Category, string[]> = {
  keyboard: ['switch', 'connection', 'size'], mouse: ['connection', 'sensitivity', 'weight', 'size'],
  headphones: ['form', 'connection', 'driver', 'size'], smartphone: ['memory', 'storage', 'screen_size'],
  laptop: ['processor_tier', 'memory', 'weight'], tablet: ['memory', 'storage', 'screen_size'],
  monitor: ['screen_size', 'resolution', 'refresh_rate'], camera: ['camera_type', 'sensor_class', 'video'],
  smartwatch: ['screen_size', 'battery_grade', 'usage'], speaker: ['speaker_type', 'power', 'connection'],
  cycling: ['equipment_type', 'usage', 'size'], fitness: ['equipment_type', 'resistance', 'usage'],
  home_appliance: ['appliance_type', 'capacity', 'power'],
}
export function productSpecs(product: Product) {
  return summaryKeys[product.category].map(key => product.attributes[key])
    .filter(value => value && value !== '无').slice(0, 3).map(String)
}
export function attributeValue(value: unknown) {
  if (Array.isArray(value)) return value.map(v => v === 'wired' ? '有线' : v === 'wireless' ? '无线' : String(v)).join(' / ')
  return String(value)
}
