# **System Design: Grid Search Analyzer v2.1 (Deterministic & Robust)**

## **1\. Objective**

To identify **Robust Parameter Plateaus** by analyzing backtest logs. The system uses strict, deterministic thresholds to classify strategy configurations, ensuring that high returns are not result of curve-fitting to specific dates.

## **2\. Architecture Overview (Dual-Mode)**

The system operates in two stages:

1. **Stage A (Summary Scan):** Reads summary.csv to cluster runs and filter out the bottom 80% of performers based on Calmar Ratio.  
2. **Stage B (Deep Dive):** Parses the daily\_log.csv for candidate runs to calculate specific Stress Test metrics.

## **3\. Module 2.5: The Robustness Engine**

This module calculates stability scores using specific mathematical definitions.

### **A. Neighbor Stability Score (The "Plateau" Test)**

For every cluster (grouped by Leverage Scalar, SMA Slow, Upper Thresh Z):

* **Definition of Neighbor:** Any run where SMA Slow is within $\\pm 10$ days and Upper Thresh Z is within $\\pm 0.1$.  
* **Calculation:**  
  1. Cluster\_Return \= Mean Total Return of the specific parameter set.  
  2. Neighbor\_Return \= Mean Total Return of all Neighbors.  
  3. Degradation \= $1 \- (\\text{Neighbor\\\_Return} / \\text{Cluster\\\_Return})$.  
* **Thresholds:**  
  * **Stable:** Degradation $\\le 0.10$ (10%).  
  * **Unstable:** Degradation $\> 0.10$.

### **B. Yearly Consistency Score**

* **Input:** Annual Returns for 2010–2024.  
* **Calculation:** Count $N$ years where Strategy\_Return \> QQQ\_Return.  
* **Threshold:**  
  * **High Consistency:** $N \\ge 10$.  
  * **Low Consistency:** $N \< 10$.

### **C. Stress Test Isolation (Deterministic Logic)**

The script must calculate the **Strategy Total Return** during these exact ISO dates and compare against the defined **Pass Thresholds**.

| Period Name | Start Date | End Date | Logic Check (Boolean) | Pass Threshold |
| :---- | :---- | :---- | :---- | :---- |
| **Volmageddon** | 2018-02-01 | 2018-02-28 | Strategy\_Ret \> Threshold | **\> \-8.0%** (QQQ was \-7.3%) |
| **Covid Crash** | 2020-02-19 | 2020-03-23 | Strategy\_Ret \> Threshold | **\> \-20.0%** (QQQ was \-27%) |
| **Inflation** | 2022-01-01 | 2022-12-31 | Strategy\_Ret \> Threshold | **\> \-20.0%** (QQQ was \-32%) |

* **Pass Logic:** A run must pass **all 3** stress tests to be considered for "TITAN" status.

## **4\. Verdict Classification Rules (Priority Queue)**

The Verdict is assigned by checking these rules in order. The first match applies.

**Definitions:**

* Benchmark\_Ret \= QQQ Buy & Hold Return.  
* Stress\_Pass \= Boolean (True if all 3 stress tests passed).  
* Plateau\_Pass \= Boolean (True if Degradation $\\le$ 10%).

| Rank | Verdict Label | Return Condition | Drawdown Condition | Robustness Condition |
| :---- | :---- | :---- | :---- | :---- |
| **1** | **TITAN CONFIG** | $\> 1.5 \\times$ Benchmark | Max DD $\> \-25.0\\%$ | Stress\_Pass AND Plateau\_Pass |
| **2** | **Efficient Alpha** | $\> 1.2 \\times$ Benchmark | Max DD $\> \-30.0\\%$ | Stress\_Pass OR Plateau\_Pass |
| **3** | **Lucky Peak** | $\> 1.5 \\times$ Benchmark | Any | Fails Robustness checks |
| **4** | **Safe Harbor** | $1.0 \\times \- 1.2 \\times$ Bench | Max DD $\> \-20.0\\%$ | Stress\_Pass |
| **5** | **Aggressive** | $\> 2.0 \\times$ Benchmark | Max DD $\< \-30.0\\%$ | Any |
| **6** | **Degraded** | $\<$ Benchmark | Any | Any |
| **7** | **Unsafe** | Any | Max DD $\< \-35.0\\%$ | Any |

## **5\. Revised Output Schema**

The final analyzer\_summary.csv must contain:

1. Cluster\_ID  
2. Avg\_Total\_Return  
3. Max\_Drawdown  
4. Calmar\_Ratio  
5. Plateau\_Stability\_% (The calculated degradation complement)  
6. Stress\_2018\_Ret  
7. Stress\_2020\_Ret  
8. Stress\_2022\_Ret  
9. Verdict

## **6\. Python Implementation Updates**

    def check\_stress\_tests(self, daily\_df):  
        """  
        Deterministic Boolean Check.  
        Returns: (bool\_pass\_all, dict\_of\_returns)  
        """  
        \# Define periods  
        periods \= {  
            '2018\_Vol': ('2018-02-01', '2018-02-28', \-0.08),  
            '2020\_Crash': ('2020-02-19', '2020-03-23', \-0.20),  
            '2022\_Bear': ('2022-01-01', '2022-12-31', \-0.20)  
        }  
          
        results \= {}  
        passed\_all \= True  
          
        for name, (start, end, threshold) in periods.items():  
            \# Filter dates  
            mask \= (daily\_df\['Date'\] \>= start) & (daily\_df\['Date'\] \<= end)  
            chunk \= daily\_df.loc\[mask\]  
              
            if chunk.empty:  
                results\[name\] \= 0.0  
                passed\_all \= False  
                continue  
                  
            \# Calc Return  
            start\_val \= chunk.iloc\[0\]\['Portfolio\_Value'\]  
            end\_val \= chunk.iloc\[-1\]\['Portfolio\_Value'\]  
            ret \= (end\_val \- start\_val) / start\_val  
              
            results\[name\] \= ret  
              
            \# Check Threshold  
            if ret \<= threshold:  
                passed\_all \= False  
                  
        return passed\_all, results  
