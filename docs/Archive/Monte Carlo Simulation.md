# **1-Pager: Monte Carlo Simulation**

## **1\. Objective**

To test the strategy's vulnerability to **luck** and **sequence risk**.

A strategy's performance can be highly dependent on the *order* of its trades. A strategy might look great because it had a lucky streak of 10 wins *before* its 3 big losses. If the 3 big losses came first, it might have blown up.

A Monte Carlo simulation "shuffles the deck" 10,000 times to see how much of your performance was due to a real edge vs. a lucky sequence of trades. It answers: **"If the order of my trades was random, what is the probability I would have failed?"**

## **2\. How-To: The Monte Carlo Algorithm**

This process is run *after* your backtest or WFO is complete.

* **Prerequisite:** A complete list of all your trades and their individual returns. The wfo\_trades\_master.csv file from the WFO test is the *perfect* input for this.

**Here is the step-by-step process to codify:**

1. **Get Trade List:** Load your wfo\_trades\_master.csv. Extract just the Return\_Percent column into a list.  
   * *Example List:* \[+5.2, \-2.1, \+8.0, \-1.5, ...\] (e.g., 500 total trades)  
2. **Define Iterations:** Choose a high number of simulations, e.g., 10,000 runs.  
3. **Start Loop (Run 1 to 10,000):**  
   * **Shuffle:** Create a *new*, *randomly shuffled* copy of the trade list.  
     * *Example Shuffled List:* \[-2.1, \+8.0, \+5.2, \-1.5, ...\]  
   * **Simulate:** Start with your Initial\_Portfolio balance (e.g., $100,000). Apply each trade from the *shuffled list* sequentially to simulate a new equity curve.  
   * **Record:** At the end of this *single* simulation, save the final metrics for this "random" run.  
     * Final\_Equity  
     * Max\_Drawdown  
     * Annualized\_Return  
4. **End Loop.**  
5. **Analyze:** You now have a results file with 10,000 possible outcomes. Plot a histogram of the Final\_Equity or Max\_Drawdown to see the statistical distribution of your strategy's edge.

## **3\. Required Files for Analysis**

### **File 1: monte\_carlo\_results.csv**

* **Contents:** A summary file containing the final metrics for all 10,000 simulations.  
* **Columns:** Run\_ID, Final\_Equity, Annualized\_Return, Max\_Drawdown

### **How to Analyze This File (The "Final Report")**

This file is your final judgment. Here is how you read it:

1. **Find Your Original Result:** Compare your *original* WFO Annualized Return (e.g., 35%) to the 10,000 simulated returns.  
   * **Robust:** Your 35% is near the *median* (50th percentile) of the simulation. This is excellent\! It means your result is statistically average and not lucky.  
   * **Lucky:** Your 35% is at the *95th percentile*. This is a red flag. It means you had to be extremely lucky to get your result, and 95% of other outcomes were worse.  
2. **Calculate Confidence Intervals:**  
   * Find the **5th Percentile** Max\_Drawdown (the "very unlucky" scenario). Can you live with this drawdown?  
   * Find the **5th Percentile** Annualized\_Return. Is this return still acceptable to you?  
3. **Calculate "Risk of Ruin":**  
   * What *percentage* of the 10,000 simulations had a Max\_Drawdown \> 50% (or any "ruin" level you define)?  
   * If the answer is 0.1%, your strategy is very safe. If the answer is 20%, your strategy is a time bomb.