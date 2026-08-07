import { PanelHead } from "@/components/PanelHead";

/** 低吸规则说明：v3 超跌反弹 + v4 趋势回踩两族因子规则的完整口径。 */
export function LowSuctionGuideView() {
  return (
    <section aria-label="低吸规则说明" className="text-sm">
      <PanelHead no="01" zh="上升趋势低吸规则（v4）" en="TREND PULLBACK" note="主升浪中的安静回踩" />
      <div className="space-y-3 border-b px-3 py-4 sm:px-4">
        <div>
          <div className="mb-1 font-semibold">前置结构（硬门槛）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>多头排列：MA5 &gt; MA10 &gt; MA20 &gt; MA30（三线），且 MA10/MA20/MA30 全部向上 —— 不硬性要求 MA60，适配长期下跌刚转势、MA60 仍在上方的情况</li>
            <li>D 日低点回踩 MA5（强趋势）或 MA10（MA5 不规律时）—— 影线触碰区间 -4% ~ +1.5%，收盘不破 -1.5%</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">基础形态：安静小 K 线（candle_quiet）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>D 日振幅 ≤ 5%（(最高-最低)/前收）—— 小阴小阳的下影线低点才算回踩，嘈杂 K 线的影线是噪音</li>
            <li>依据：全量 811 日最单调变量 —— 振幅 &lt;3% 组 +0.013% → ≥10% 组 <span className="text-emerald-600">-0.734%</span></li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">否决 1：首阴追高（trend_first_crack_chase）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>振幅 &gt;5% 且收盘没回到 MA5（距 MA5 ≥ 0）且<span className="text-foreground">昨日仍在涨</span> —— 大涨后的第一根分歧巨震，追高买首阴</li>
            <li>昨日已跌 = 分歧已开始释放，才算低吸语境；全量单调：昨日 &lt;-5% 组 -0.058% → 昨日 ≥5% 组 <span className="text-emerald-600">-0.867%</span></li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">否决 2：趋势过伸（trend_overextended）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>当前 M5-M10 距离 ≥ 本段多头趋势内此前每次回踩日距离中位数 + 2 个百分点 —— 相对本段自己的回踩签名判断趋势老嫩，不用绝对阈值</li>
            <li>全区间单调：超额 &lt;0 组 -0.134% → ≥6 组 <span className="text-emerald-600">-1.049%</span></li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">落地规则与验证</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li><span className="text-foreground">安静小K线回踩（v4_quiet）</span>：多头排列 + 安静 K 线低点回踩 MA5/MA10 + 非过伸 —— 最纯形态</li>
            <li><span className="text-foreground">真实回踩（v4_authentic）</span>：多头排列 + 低点回踩 + 非首阴追高 + 非过伸 —— 通用形态</li>
            <li>验证：6/6 趋势坏样本全部命中否决；8/8 个人案例零误伤；官方案例门禁 15/15；全量均值 -0.008% 打赢全部同族基线（-0.092~-0.120）</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">综合评分构成（0-100）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>振幅安静度(语境) 22 + 趋势年龄 14（6-10 天满分）+ 回踩线别 14（MA5=14 / MA10=9）+ 换手率梯度 12（&lt;3% 满分，不门禁）</li>
            <li>连续小 K 线 14（≥5 根满分）+ 昨日已跌 8 + 收盘位置 8 + 趋势老嫩 5 + 当日缩量 3</li>
            <li>语境调节：转势票(MA60&gt;MA30) 中等振幅 5-8% 反而满分（反弹启动特征 +0.018%）；成熟票需极安静 &lt;3%（同区间 -0.583%）</li>
          </ul>
        </div>
      </div>

      <PanelHead no="02" zh="超跌反弹低吸规则（v3）" en="OVERSOLD REBOUND" note="长期空头后的上穿过程回踩" />
      <div className="space-y-3 border-b px-3 py-4 sm:px-4">
        <div>
          <div className="mb-1 font-semibold">前置结构（硬门槛）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>长期空头排列后，MA10 处于分阶段上穿过程：MA10 先上穿 MA20 / 双上穿 / MA5-MA10 联合上攻 / MA10 已上穿 MA30（15 日内）之一成立</li>
            <li><span className="text-foreground">超跌/趋势互斥</span>：MA10&gt;MA20&gt;MA30 三线多头排列一旦成立，就不再纳入超跌族（多头已成 = 趋势族，超跌仅指空头→多头过渡期）—— 防止已走成多头的票混进超跌族拿满分</li>
            <li><span className="text-foreground">低吸位置</span>：D 日必须处于「M10 准备上穿 M30」(M10 在 M30 下方) 或「穿完回贴 M30」(贴近) 的地方，最低价回踩 M10 获支撑 —— 排除 M10 已远穿 M30（上穿过程结束）的横盘票，它们不是"准备上穿处的回踩"</li>
            <li><span className="text-foreground">low 真贴 M10</span>：最低价必须真正回踩触及/跌破 M10（low 距 M10 ≤ +1.0%），不是靠宽阈值"擦"到 M10 上方 —— 排除 low 没到 M10 的冲高型假回踩（主人研究票 low 到 M10 全部 ≤ +0.59%）</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">核心 1：低点获均线实际支撑</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>D 日低点在 MA10/MA20/MA30 获实际支撑且收盘有反应 —— 缩量贴死低点 = 接飞刀，必须看到收盘脱离</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">核心 2：换手率门禁（唯一全段单调变量）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>换手率 &lt;3% 最优（-0.07% 组）、&lt;8% 为门禁线；≥8% 组 -0.53% —— 高换手 = 派发不是吸筹</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">核心 3：崩盘日紧凑反弹</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>MA10 上穿后回贴 MA30 的崩盘日：换手 &lt;3% 且收盘脱离低点 0.3~1.5% —— 研究中唯一全时间段为正的形态</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">综合评分构成（0-100）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>换手率门禁 gate（≥8% 派发，失败总分封顶 39）+ 换手率梯度 14（&lt;3% 满）+ 振幅安静度 12 + 低点支撑 16 + 空头持续时长 10（≥20 日满）</li>
            <li>上穿过程结构 12 + 崩盘脱离低点 10 + 收盘支撑反应 8 + 梯形缩量 5 + 连续小 K 线 3 + 量能趋势 10（5/10 日均量比 &lt;0.8 骤缩满 → ≥1.3 骤放 0）</li>
          </ul>
        </div>
      </div>

      <PanelHead no="03" zh="口径与边界" en="CONVENTION" note="诚实边界，不外推" />
      <div className="space-y-2 px-3 py-4 text-muted-foreground sm:px-4">
        <ul className="ml-4 list-disc space-y-0.5">
          <li>数据口径：raw_unadjusted 不复权日线（探索级，除权日有已知污染）；D+1 收盘到收盘收益，未扣费</li>
          <li>回测结论（752 交易日）：每日综合分最高的趋势 1 只 + 超跌 1 只两仓模拟，三年复利 +53.0%、最大回撤 -23.8%（趋势单仓 +9.9% / 超跌单仓 +92.9%）</li>
          <li>分数段：超跌 60-79 / 80-89 / 90-100 三段 validation+holdout 双段为正（推荐区间）；趋势族各段 holdout 为负、暂不推荐，超额难靠日线因子稳定捕获</li>
          <li>并列决胜：超跌顶分并列率超九成 —— 并列时按连续小 K 线数更多、换手率更低决胜（均为全量验证的单调方向），回测与实时推荐同一决胜键</li>
          <li>行情主导一切：两族人口均值仅接近打平，本产品按综合分排序取最高，不做全池买入</li>
          <li>实时推荐：交易日内每 30 分钟用现货快照合成当日虚拟 K 线重算（未定型），收盘后以日线同步确认为准；实时组不含 ST 股</li>
        </ul>
        <div className="rounded border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-600">
          ⚠️ 全部内容为历史回测与研究结论，非投资建议；样本外有效性不保证，极端行情下 D+1 仍可能大幅亏损。
        </div>
      </div>
    </section>
  );
}
