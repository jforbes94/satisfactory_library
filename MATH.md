# How this factory report is calculated

Everything is in **items per minute**. No numbers are hidden; here is every formula.

## 1. Rate of a single machine
```
rate = quantity_per_craft * 60 / craft_time_seconds
```
A Screw Constructor makes 4 screws per 6 s = 4 * 60 / 6 = **40 screws/min**.

## 2. Item balance across the whole factory
```
made[item]     = sum over producers of (machines * rate_out)
needed[item]   = sum over consumers of (machines * rate_in)
supplied[item] = made / needed        (>= 100% is healthy)
```

## 3. Line efficiency
```
efficiency(line) = min over its inputs of supplied[input]   (capped at 100%)
```
Raw resources (ore, coal, water, leaves) are assumed fully supplied. This is a
first-order measure: it uses each input's nameplate output and does not chain
multiple starvations together.

## 4. Power
```
power(line) = base_MW * sum over machines of clock**1.6
```
Underclocking a machine saves power faster than it cuts output (exponent 1.6),
which is why 'round up and underclock the last machine' is a real saving.

## 5. Bottleneck ranking
Items where `supplied < 100%`, sorted by lowest supplied first, then biggest
shortfall. The smallest fix is `ceil(shortfall / output_per_machine)` more machines.

### This factory's biggest bottleneck
- **Modular Engine** — running at 11%, made 1/min vs needed 8.75/min (7.75/min short).
- Fix: add 8 Manufacturer on Modular Engine.

## Graph metrics
- **Bottleneck (weakest link):** lowest supply ratio in the graph.
- **Longest chain (longest path):** most steps from a raw resource to a product.
- **Biggest hub (out-degree):** the item feeding the most lines.
- **Sub-factories (connected components):** machine groups that connect to each
  other but not to the rest (your biomass chain is separate).
- **Sources / sinks:** raw inputs (in-degree 0) and final products (out-degree 0).
