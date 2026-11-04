// Register only the ECharts pieces this app uses. Importing from 'echarts' directly
// pulls in every chart type and component (~1.1 MB minified).
import { init, use as registerComponents } from 'echarts/core'
import { LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

registerComponents([PieChart, LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

export { init }
