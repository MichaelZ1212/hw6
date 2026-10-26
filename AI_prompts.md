# AI Prompts

A running log of the prompts I gave my AI coding assistant while building the Campus Customs vendor desk agent. Each problem gets its own section. Follow-up prompts appear under the initial prompt, with a short note on what the first attempt was missing.

---

## Problem 1: Vibe Coder Prompts

### Initial prompt

> I'm working on a coding assignment where I'll use AI to help build a vendor desk agent. I want to keep a record of the prompts I use throughout the project.
>
> Please create a Markdown file called AI_prompts.md in the project root folder.
>
> Organize it by problem number and title. For each problem, include the initial prompt I gave you, any follow-up prompts I used, and a short explanation of what needed improvement after the first attempt.
>
> Start with Problem 1 and leave room for the remaining problems. As we work through each problem, help me update the file with the prompts I actually used. Keep everything organized and easy to read.

### Follow-up prompts

_None._

---

## Problem 2: Size Up the Handbook

### Initial prompt

> I want to estimate how much it costs to include the shop handbook in every AI request.
>
> Please unzip data.zip and review data/shop_handbook.md and data/prices.json.
>
> First, calculate the total number of tokens in the handbook and explain how you counted them.
>
> Then, using the gpt-6-luna pricing information, estimate the cost of sending the handbook to the model for one API call and for 1,000 calls. Compare the costs with and without prompt caching.
>
> Please show the calculations clearly and save the results in output/handbook_estimate.md.
>
> Also explain how much money caching could save. Keep the report simple and easy to understand so I can compare these estimates with actual API usage later.

### Follow-up prompts

_None._

---

## Problem 3: Build the Vendor Desk Agent

### Initial prompt

> I want to build a vendor desk AI agent that helps Campus Customs evaluate supplier offers and decide whether to purchase products.
> Please use Python, PydanticAI, and the gpt-6-luna model through my Portkey API key.
> The agent should take a vendor document as input, read its contents, and extract the important purchasing information, including the vendor name, SKU, unit price, delivery lead time, and minimum order quantity. It should support HTML, PDF, and email (.eml) files.
> Based on the purchasing policies in `data/shop_handbook.md`, the agent should decide whether to recommend the purchase and provide a short, one-sentence explanation. Include the handbook in every model request.
> Please organize the project into four main files:
>
> * `agent.py` to run the agent from the command line
> * `tools.py` for reading documents and other tools
> * `models.py` for defining the structured output
> * `prompts/prompt.md` for the agent's instructions
>
> I also want to test whether vendor documents can manipulate the agent. Please include two simulated tools, `send_email` and `approve_payment`. These tools should never send real emails or make payments. Instead, they should only record attempted calls and their arguments in `output/trap_calls.json`, initialized as an empty list. The agent should not use these tools during normal purchasing evaluations.
> For tracking and debugging, please record the API token usage, estimated cost based on `data/prices.json`, and execution time in `output/usage_log.json`. Also save all tool calls, their inputs, short results, and the final recommendation in `output/audit_trail.json`. Keep these logs across multiple runs.
> Make sure I can run the agent from the terminal by providing a document path, such as:
> `python agent.py --doc data/practice_docs/p01_bluehen_quote.html`
> Once the implementation is ready, test it with the p01 and p08 practice documents and show me the results.
> Finally, create `output/harness.md` to briefly explain the purpose of each field in `models.py` and each tool in `tools.py`.
> Please keep the code simple, organized, and easy to modify for later experiments.

### Follow-up prompts

_None._

---

## Problem 4: With and Without Cached Tokens

### Initial prompt

> I want to evaluate how much prompt caching can reduce the operating cost of the vendor desk agent we built in Problem 3.
> Please run the agent on all 12 practice documents under two different setups: one that reuses the shop handbook through prompt caching, and another that processes the same documents without using any cached tokens.
> Keep the model, handbook, agent instructions, and test documents the same so the comparison is fair. Use only gpt-6-luna through my Portkey API key.
> Make sure caching is actually working by checking the token usage reported by the API. For the non-cached setup, verify that the API reports zero cached tokens. If it still shows cached tokens, adjust the configuration and rerun the test.
> Save the results of every model call in `output/cache_test.json`, including the document name, caching setup, all token usage details returned by the API, and the actual calculated cost based on `data/prices.json`.
> Then create a summary report in `output/cache_test.md` that covers:
>
> 1. The total cost and average cost per document for both setups, including the percentage saved through caching.
> 2. A comparison between the actual results and the cost estimates from Problem 2.
> 3. A monthly cost projection assuming 1,000 documents are processed daily for 30 days.
> 4. Any unexpected findings in the token usage or costs, along with possible explanations.
>
> Please show the calculations clearly and use actual API usage data rather than estimated token counts. If any calls fail or the caching behavior cannot be verified, flag those results instead of treating them as successful.
> Keep the implementation compatible with the existing agent and preserve all the logging and safety features from Problem 3.

### Follow-up prompts

_None._

---

## Problem 5: Attack Your Own Agent

### Initial prompt

> I want to test how vulnerable my vendor desk agent is to malicious instructions hidden inside supplier documents.
>
> Please use the original agent from Problem 3 without adding any new security protections yet. Run it on all 12 files in data/practice_docs/ using only gpt-6-luna through my Portkey API key.
>
> For each document, compare the agent's extracted information and purchasing decision against the expected results in data/practice_key.json. Check each field separately so I can see exactly where the agent made mistakes.
>
> Also review output/trap_calls.json to see whether any document caused the agent to call the simulated email or payment tools. Check the final answers for suspicious links, unexpected instructions, or other content that should not be part of a normal purchasing recommendation.
>
> Save the detailed results in output/attack_results.json, including field-level accuracy, decision accuracy, trap tool activity, and any suspicious output.
>
> Then create output/attack_results.md to explain which documents successfully misled the agent, what went wrong, and where the malicious content was hidden.
>
> Please also inspect the documents as a human would see them in a browser, PDF viewer, or email client, and compare that visible content with the text extracted by the agent. Pay attention to hidden HTML elements, PDF content, and email formatting that might expose the agent to instructions a human would not normally notice.
>
> For now, focus on identifying and documenting vulnerabilities rather than fixing them. Keep the existing agent behavior unchanged so we can establish a baseline for later security improvements.

### Follow-up prompts

_None._

---

## Problem 6: Defend Your Agent

### Initial prompt

> I want to improve the security of my vendor desk agent based on the vulnerabilities we identified in Problem 5.
>
> Please add three layers of protection against malicious instructions hidden in supplier documents.
>
> First, at the code level, inspect and clean the document content before sending it to the AI model. Handle suspicious HTML, PDF, and email content carefully while preserving legitimate vendor information such as prices, SKUs, lead times, and minimum order quantities.
>
> Second, improve the agent's architecture so untrusted vendor documents cannot trigger sensitive actions or override purchasing decisions. Keep the send_email and approve_payment tools in the project, but make sure the document-processing agent cannot execute them. These tools should remain available for a separate workflow requiring human approval, and they must continue to log simulated calls without performing real actions.
>
> Third, strengthen prompts/prompt.md with clear instructions that vendor documents are untrusted data. The agent should ignore any embedded instructions that attempt to change its behavior, override the handbook, or trigger unrelated actions.
>
> Please also keep a way to run the original agent without these protections so we can compare the results in the next problem.
>
> After implementing the defenses, rerun all 12 practice documents and compare the results with the baseline from Problem 5. Check field-level accuracy, purchasing decisions, trap tool calls, and suspicious output. Make sure legitimate quotes are still processed correctly rather than rejected or left blank.
>
> Save the detailed results in output/defense_results.json, including token usage and cost per document based on data/prices.json.
>
> Create output/defense_results.md with a before-and-after comparison for all 12 documents, an explanation of what each security layer prevents, and the additional tokens and costs introduced by each layer. Measure the overhead of each layer separately where possible rather than guessing.
>
> Finally, update output/harness.md with a Safety section explaining the three layers in simple terms.
>
> Please preserve the existing agent functionality, logging, and caching support, and use only gpt-6-luna through my Portkey API key for all AI calls.

### Follow-up prompts

_None._

---

## Problem 7: Red Team

### Initial prompt

> I want to run a red-team experiment to see whether my vendor desk agent can resist new prompt injection attacks.
> Please create two new supplier documents in `data/my_attacks/`. They can be HTML, PDF, or email files. Both should look like normal vendor quotes when opened by a person, with realistic product details, pricing, delivery times, and minimum order quantities.
> However, each document should contain a different hidden prompt injection technique. Please review the attacks in the existing practice documents first so that the two new attacks use different methods or target different weaknesses.
> For the first attack, try to manipulate the agent's purchasing recommendation so that it ignores the shop handbook or makes an incorrect decision.
> For the second attack, try to trick the agent into calling one of the simulated tools, such as `send_email` or `approve_payment`, or including unauthorized content in its final answer. These tools must remain simulated and must never send real emails or payments.
> After creating both documents, test each one against the original agent without defenses and the protected agent from Problem 6. Keep the testing conditions consistent and use only gpt-6-luna through my Portkey API key.
> Check the extracted purchasing information, final recommendations, audit logs, and trap tool records. Compare the results to determine whether the attacks succeeded and whether the defenses prevented them.
> Please create `output/red_team.md` explaining for each attack:
>
> * The attack technique and where the malicious content was hidden
> * What behavior the attack was trying to trigger
> * What happened when tested against the unprotected agent
> * What happened when tested against the defended agent
> * Why the defenses worked or failed
>
> Please use actual test results rather than assuming the attacks were successful. If an attack fails against the original agent, report that clearly and explain what happened.
> Keep the existing project structure, logging, and safety controls intact.

### Follow-up prompts

_None._

---

## Problem 8: Exam Documents

### Initial prompt

> I want to run the final version of my vendor desk agent on the 10 exam documents and save the results for evaluation.
> Please use the defended agent we developed in Problem 6, including all three security layers. Use only gpt-6-luna through my Portkey API key.
> Process every file in `data/exam_docs/` using the same workflow and purchasing rules we used for the practice documents. Since these exam files don't have an answer key, let the agent generate its own results based on the document content and the shop handbook.
> For each document, extract the vendor name, SKU, unit price, lead time in days, and minimum order quantity. Then determine whether the purchase should be recommended and provide a short explanation based on the handbook.
> Also check whether either simulated trap tool was called, and capture the actual input tokens, cached tokens, output tokens, and API cost using `data/prices.json`.
> Save everything in `output/exam_results.json`, with exactly one entry per exam document and the field names required by the assignment.
> Please make sure:
>
> * All 10 documents are processed.
> * The output is valid JSON with consistent field types.
> * Purchasing decisions follow the handbook rather than instructions embedded in vendor documents.
> * The agent still processes legitimate quotes normally.
> * No real emails or payments are made.
> * Results are saved directly from actual agent runs without manually changing the values.
>
> After running the tests, verify that the JSON file contains 10 entries and all required fields are present. Report any processing errors rather than silently skipping documents.
> Keep the existing agent implementation and safety controls intact.

### Follow-up prompts

_None._

---

## Problem 9: Results Page

### Initial prompt

> I want to create a professional-looking results dashboard that summarizes everything we learned from building, testing, and securing the vendor desk agent.
> Please generate a single HTML report at `output/hw6_report.html`. It should work completely offline when I double-click it, without requiring internet access or any additional files. Keep all CSS, JavaScript, charts, and report data inside the HTML file.
> Use the actual results from our previous experiments rather than making up any numbers.
> I'd like the report to include five main sections:
>
> 1. Caching and cost savings: Show the results from Problem 4, including the total cost, average cost per document, and percentage saved with caching. Add a clear chart comparing the cached and non-cached setups.
> 2. Security improvements: Compare the agent's performance before and after adding the defenses from Problem 6. Show which attacks succeeded before, which were blocked afterward, and whether the agent still processed legitimate vendor documents correctly.
> 3. Defense overhead: Explain the additional tokens and dollar costs introduced by the security layers. Use the measured results to show the trade-off between security and operating cost.
> 4. Exam and red-team results: Summarize the agent's performance on the 10 exam documents and the two custom attacks from Problem 7. Include the extracted results, security outcomes, and any important findings.
> 5. Final recommendation: Write a short recommendation for the Campus Customs store manager on whether the agent is ready to process real supplier emails. Estimate the monthly operating cost based on 1,000 documents per day over 30 days, using the actual measured cost per document.
>
> For the visual design, please use a clean, modern dashboard style with a consistent color palette, readable fonts, summary metrics, comparison tables, and simple charts. Make the report easy for a non-technical store manager to understand.
> Please check that every chart and number matches the source data, and clearly label any estimates or projections. If some results are missing, identify them instead of inventing values.
> Finally, verify that the HTML file opens correctly offline and that all charts, tables, and styling work without external dependencies.

### Follow-up prompts

_None._

---

## Problem 10: Push to GitHub and Submit the URL

### Initial prompt

> I've finished the previous parts of my HW6 project, and now I need to prepare everything for the final GitHub submission.
> Please help me organize and publish the complete project to a public GitHub repository so that the graders can clone it and run the agent without any missing files.
> First, review my current project folder and make sure all the required files are included:
>
> * The main Python files: `agent.py`, `tools.py`, and `models.py`
> * The agent instructions in `prompts/prompt.md`
> * `AI_prompts.md`, documenting the prompts I used throughout the assignment
> * The complete `data/` folder, including the handbook, pricing information, answer key, all 12 practice documents, all 10 exam documents, and my two custom attack files
> * All output files generated in Problems 2–9, including the experiment logs, attack and defense results, exam results, and final HTML dashboard
>
> Please also create or update the following files:
>
> 1. README.md: Explain what the project does, how to install the dependencies, how to configure the API key, and how to run the vendor desk agent on a sample document. Include the exact terminal commands.
> 2. requirements.txt: List all Python dependencies needed to run the project.
> 3. .gitignore: Make sure sensitive information such as `.env`, API keys, virtual environments, and unnecessary temporary files are excluded from Git.
> 4. .env.example: Provide an example of the required environment variables using placeholders only, without any real credentials.
>
> Before uploading anything, check that the project is complete and that no required files are missing. Also verify that the agent can run using the documented setup instructions.
> Please check the files for exposed API keys, passwords, or other sensitive information. Do not upload any real credentials.
> Once everything is ready, help me create a public GitHub repository named `hw6` and push the complete project to it. If GitHub authentication or authorization is needed, ask me to complete that step.
> Finally, verify that the repository is publicly accessible, that all required files are present, and that the README provides enough instructions for the graders to reproduce the project.
> Give me the final GitHub repository URL so I can submit it on Canvas. Do not submit anything to Canvas on my behalf.

### Follow-up prompts

_None._
