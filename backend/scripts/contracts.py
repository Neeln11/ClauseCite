"""Realistic seed contracts.

"Test Document 1" undermines every other claim the project makes, so the corpus
is written as four plausible instruments a small firm would actually hold: a
commercial lease, a master services agreement, a mutual NDA, and an employment
contract.

The text is deliberately shaped to exercise the pipeline rather than merely fill
pages:

- **All-caps article headings** and **short numbered sub-headings** give the
  chunker a real `section_path` ("ARTICLE 3 - TERMINATION > 3.2 Notice Period").
- **Numbered clauses** are the hard split candidates the chunker looks for.
- **Specific, checkable facts** (ninety days, 4,062.50, 99.5%, 250,000) are what
  a user actually asks about, and what makes a wrong answer obvious.
- **One deliberate cross-document conflict**: the lease's termination notice is
  ninety days while the employment agreement's is three months. Asking "what is
  the notice period?" across all documents is the demo that shows the model
  surfacing both sources rather than picking one.

Nothing here is legal advice or a usable template; it is synthetic text written
to look like the real thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Section:
    """One article: an all-caps heading, then (sub-heading, paragraphs) pairs."""

    heading: str
    clauses: list[tuple[str, list[str]]] = field(default_factory=list)


@dataclass(slots=True)
class Contract:
    filename: str
    title: str
    subtitle: str
    parties: list[str]
    sections: list[Section]


HENDERSON_LEASE = Contract(
    filename="Henderson_Commercial_Lease.pdf",
    title="COMMERCIAL LEASE AGREEMENT",
    subtitle="Unit 4, 118 Calder Street, Leeds LS1 4RT",
    parties=[
        "THIS LEASE is made on 12 February 2024 between MARCHETTI HOLDINGS LLC, "
        "a limited liability company whose registered office is at 40 Wellington "
        "Street, Leeds LS1 2DE (the \"Landlord\"), and HENDERSON OPTICAL LIMITED, "
        "a company registered in England and Wales under number 09447213 whose "
        "registered office is at 118 Calder Street, Leeds LS1 4RT (the \"Tenant\").",
        "The Landlord and the Tenant are each a \"party\" and together the "
        "\"parties\". The parties agree as follows.",
    ],
    sections=[
        Section(
            heading="ARTICLE 1 - PREMISES AND TERM",
            clauses=[
                (
                    "1.1 Premises",
                    [
                        "The Landlord lets to the Tenant the ground floor premises known as "
                        "Unit 4, 118 Calder Street, Leeds LS1 4RT, comprising approximately "
                        "2,450 square feet of net internal area as shown edged red on the plan "
                        "annexed at Schedule 1 (the \"Premises\"), together with the right to "
                        "use in common with the Landlord and other tenants the entrance hall, "
                        "staircases, and six allocated parking spaces in the rear yard.",
                        "The Premises exclude the roof, the exterior walls, and all structural "
                        "parts of the building, which are retained by the Landlord.",
                    ],
                ),
                (
                    "1.2 Term",
                    [
                        "The term of this Lease is five (5) years commencing on 1 March 2024 "
                        "and expiring on 28 February 2029, unless terminated earlier in "
                        "accordance with Article 3.",
                        "This Lease is excluded from the security of tenure provisions of "
                        "sections 24 to 28 of the Landlord and Tenant Act 1954, the parties "
                        "having made the requisite declarations before this Lease was entered "
                        "into.",
                    ],
                ),
                (
                    "1.3 Permitted Use",
                    [
                        "The Tenant shall use the Premises only as a retail optician's practice "
                        "and dispensing laboratory within Class E of the Town and Country "
                        "Planning (Use Classes) Order 1987, and for no other purpose without "
                        "the Landlord's prior written consent, which shall not be unreasonably "
                        "withheld.",
                        "The Tenant shall not use the Premises for any auction, any trade "
                        "producing noise audible outside the Premises after 18:00, or any "
                        "activity that would invalidate the Landlord's insurance.",
                    ],
                ),
            ],
        ),
        Section(
            heading="ARTICLE 2 - RENT AND OUTGOINGS",
            clauses=[
                (
                    "2.1 Base Rent",
                    [
                        "The Tenant shall pay to the Landlord an annual base rent of FORTY-EIGHT "
                        "THOUSAND SEVEN HUNDRED AND FIFTY POUNDS (48,750.00) exclusive of VAT, "
                        "payable in equal monthly instalments of 4,062.50 in advance on the "
                        "first day of each calendar month.",
                        "The first instalment shall be paid on the date of this Lease and shall "
                        "be apportioned for the period from 1 March 2024 to 31 March 2024. Rent "
                        "shall be paid by standing order to the account nominated by the "
                        "Landlord, without deduction, set-off, or counterclaim.",
                    ],
                ),
                (
                    "2.2 Rent Review",
                    [
                        "The base rent shall be reviewed on the third anniversary of the "
                        "commencement date, being 1 March 2027 (the \"Review Date\"), to the "
                        "open market rental value of the Premises on that date, assuming a "
                        "willing landlord and a willing tenant, a term of five years, and "
                        "vacant possession.",
                        "The reviewed rent shall not in any event be less than the base rent "
                        "payable immediately before the Review Date. If the parties have not "
                        "agreed the reviewed rent within two months of the Review Date, it "
                        "shall be determined by a single surveyor appointed by the President of "
                        "the Royal Institution of Chartered Surveyors, acting as an expert and "
                        "not as an arbitrator, whose fees shall be borne equally.",
                    ],
                ),
                (
                    "2.3 Service Charge",
                    [
                        "The Tenant shall pay a service charge equal to 15.4 per cent of the "
                        "Landlord's total expenditure on the maintenance, cleaning, lighting, "
                        "and insurance of the common parts of the building, that percentage "
                        "being the ratio of the net internal area of the Premises to the net "
                        "internal area of the building as a whole.",
                        "The service charge is payable quarterly in advance on the usual "
                        "quarter days, on account of an estimate provided by the Landlord "
                        "before the start of each service charge year, with a balancing payment "
                        "or credit within twenty-eight days of the Landlord issuing certified "
                        "accounts for that year.",
                    ],
                ),
                (
                    "2.4 Late Payment",
                    [
                        "Any sum payable under this Lease which remains unpaid for more than "
                        "seven days after its due date shall bear interest at four (4) per cent "
                        "per annum above the base lending rate of Barclays Bank plc from the "
                        "due date until payment, whether before or after judgment.",
                    ],
                ),
            ],
        ),
        Section(
            heading="ARTICLE 3 - TERMINATION",
            clauses=[
                (
                    "3.1 Break Right",
                    [
                        "Either party may terminate this Lease with effect from 1 March 2027 or "
                        "any date thereafter by serving notice in accordance with clause 3.2. "
                        "The Tenant's break right is conditional upon the Tenant having paid all "
                        "rent due up to the termination date and giving vacant possession.",
                    ],
                ),
                (
                    "3.2 Notice Period",
                    [
                        "Either party may terminate this agreement upon ninety (90) days prior "
                        "written notice served on the other party at the address given in "
                        "clause 7.2. Notice once served is irrevocable except with the written "
                        "agreement of both parties.",
                        "A notice served under this clause shall specify the intended "
                        "termination date and shall be of no effect if it specifies a date "
                        "earlier than ninety days after the date of service.",
                    ],
                ),
                (
                    "3.3 Effect of Termination",
                    [
                        "Upon termination, all outstanding obligations of the Tenant accrued to "
                        "the termination date shall become immediately due and payable, and the "
                        "Tenant shall remove all its fixtures, fittings, and signage and make "
                        "good any damage caused by that removal.",
                        "Rent paid in respect of any period after the termination date shall be "
                        "refunded to the Tenant within twenty-one days. Termination does not "
                        "affect either party's accrued rights or the continuing effect of "
                        "clauses 5.2 and 7.1.",
                    ],
                ),
                (
                    "3.4 Landlord's Right to Re-enter",
                    [
                        "The Landlord may re-enter the Premises and terminate this Lease "
                        "immediately if the Tenant fails to pay rent within twenty-one days of "
                        "its due date, commits a material breach of any other obligation and "
                        "fails to remedy it within thirty days of written notice, or enters "
                        "into liquidation, administration, or any voluntary arrangement with "
                        "its creditors.",
                    ],
                ),
            ],
        ),
        Section(
            heading="ARTICLE 4 - REPAIR AND ALTERATIONS",
            clauses=[
                (
                    "4.1 Tenant's Repairing Obligation",
                    [
                        "The Tenant shall keep the interior of the Premises, including all "
                        "internal surfaces, shopfront, glazing, and service installations "
                        "exclusively serving the Premises, in good and substantial repair and "
                        "condition, damage by an insured risk excepted.",
                        "The Tenant shall have the heating and ventilation plant serving the "
                        "Premises inspected and serviced by a qualified contractor at least "
                        "once in every twelve-month period and shall produce the service "
                        "records to the Landlord on reasonable request.",
                    ],
                ),
                (
                    "4.2 Alterations",
                    [
                        "The Tenant shall make no structural alteration to the Premises. "
                        "Non-structural alterations, including the installation of consulting "
                        "room partitions, require the Landlord's prior written consent, which "
                        "shall not be unreasonably withheld or delayed.",
                        "At the end of the term the Tenant shall, if the Landlord so requires "
                        "by notice given not less than three months before the term ends, "
                        "reinstate the Premises to the condition recorded in the schedule of "
                        "condition annexed at Schedule 2.",
                    ],
                ),
            ],
        ),
        Section(
            heading="ARTICLE 5 - INSURANCE AND INDEMNITY",
            clauses=[
                (
                    "5.1 Landlord's Insurance",
                    [
                        "The Landlord shall insure the building against loss or damage by fire, "
                        "flood, storm, escape of water, and other risks the Landlord reasonably "
                        "considers prudent, in the full reinstatement cost, and shall recover "
                        "the premium from the Tenant as part of the service charge.",
                    ],
                ),
                (
                    "5.2 Tenant's Insurance and Indemnity",
                    [
                        "The Tenant shall maintain public liability insurance with a limit of "
                        "indemnity of not less than five million pounds (5,000,000) for any one "
                        "occurrence, and professional indemnity insurance appropriate to the "
                        "practice of optometry with a limit of not less than two million pounds "
                        "(2,000,000).",
                        "The Tenant shall indemnify the Landlord against all liabilities, "
                        "claims, and reasonable costs arising from any breach of this Lease by "
                        "the Tenant or from any act or omission of the Tenant, its employees, "
                        "or its visitors. This clause 5.2 survives termination of this Lease.",
                    ],
                ),
            ],
        ),
        Section(
            heading="ARTICLE 6 - ASSIGNMENT AND SUBLETTING",
            clauses=[
                (
                    "6.1 Assignment",
                    [
                        "The Tenant shall not assign this Lease without the Landlord's prior "
                        "written consent, which shall not be unreasonably withheld. The "
                        "Landlord may require, as a condition of consent, that the Tenant "
                        "enter into an authorised guarantee agreement in respect of the "
                        "assignee's obligations.",
                    ],
                ),
                (
                    "6.2 Subletting and Sharing",
                    [
                        "The Tenant shall not sublet part only of the Premises. The Tenant may "
                        "share occupation of the Premises with a company in the same group, "
                        "provided no relationship of landlord and tenant arises and the Tenant "
                        "notifies the Landlord in writing within fourteen days.",
                    ],
                ),
            ],
        ),
        Section(
            heading="ARTICLE 7 - GENERAL PROVISIONS",
            clauses=[
                (
                    "7.1 Governing Law and Jurisdiction",
                    [
                        "This Lease and any dispute arising out of it are governed by the law of "
                        "England and Wales, and the parties submit to the exclusive "
                        "jurisdiction of the courts of England and Wales.",
                    ],
                ),
                (
                    "7.2 Notices",
                    [
                        "Notices under this Lease must be in writing and delivered by hand or "
                        "sent by first class recorded post to the Landlord at 40 Wellington "
                        "Street, Leeds LS1 2DE, marked for the attention of the Estates "
                        "Manager, and to the Tenant at the Premises. A notice sent by recorded "
                        "post is deemed served on the second working day after posting.",
                        "Notice by electronic mail is not valid service under this Lease.",
                    ],
                ),
                (
                    "7.3 Entire Agreement",
                    [
                        "This Lease constitutes the entire agreement between the parties and "
                        "supersedes all prior heads of terms and representations. Nothing in "
                        "this clause limits liability for fraudulent misrepresentation.",
                    ],
                ),
            ],
        ),
    ],
)


BRIGHTLINE_MSA = Contract(
    filename="Brightline_Master_Services_Agreement.pdf",
    title="MASTER SERVICES AGREEMENT",
    subtitle="Data platform engineering and support services",
    parties=[
        "THIS AGREEMENT is dated 3 September 2024 and is made between BRIGHTLINE "
        "ANALYTICS LIMITED, registered in England and Wales under number 11238907, "
        "whose registered office is at 7 Finsbury Circus, London EC2M 7EA (the "
        "\"Client\"), and NORWOOD DATA SYSTEMS LIMITED, registered in England and "
        "Wales under number 08811246, whose registered office is at Wharf House, "
        "12 Bridgewater Place, Manchester M1 5BE (the \"Supplier\").",
    ],
    sections=[
        Section(
            heading="ARTICLE 1 - SERVICES",
            clauses=[
                (
                    "1.1 Scope",
                    [
                        "The Supplier shall provide the design, implementation, and ongoing "
                        "support of the Client's data platform as described in each statement "
                        "of work agreed and signed by both parties (each an \"SOW\"). This "
                        "Agreement governs every SOW; where an SOW conflicts with this "
                        "Agreement, this Agreement prevails unless the SOW expressly states "
                        "the clause it overrides.",
                    ],
                ),
                (
                    "1.2 Personnel",
                    [
                        "The Supplier shall assign suitably qualified personnel and shall not "
                        "replace any person named as key personnel in an SOW without the "
                        "Client's prior written consent, except where that person leaves the "
                        "Supplier's employment or is absent through illness.",
                        "The Supplier remains responsible for the acts and omissions of its "
                        "subcontractors as if they were its own.",
                    ],
                ),
                (
                    "1.3 Client Obligations",
                    [
                        "The Client shall provide timely access to systems, data, and personnel "
                        "reasonably required by the Supplier. Where the Supplier is delayed by "
                        "the Client's failure to do so, agreed timescales are extended by the "
                        "period of delay and the Supplier may charge for standing time at the "
                        "rates in the relevant SOW.",
                    ],
                ),
            ],
        ),
        Section(
            heading="ARTICLE 2 - FEES AND PAYMENT",
            clauses=[
                (
                    "2.1 Fees",
                    [
                        "The Client shall pay the fees set out in each SOW. Unless an SOW states "
                        "otherwise, professional services are charged at a daily rate of one "
                        "thousand one hundred pounds (1,100.00) per consultant day exclusive of "
                        "VAT, and the monthly platform support retainer is nine thousand five "
                        "hundred pounds (9,500.00) exclusive of VAT.",
                        "Rates may be increased once in any twelve-month period on sixty days "
                        "written notice, by no more than the annual increase in the Consumer "
                        "Prices Index published immediately before the notice.",
                    ],
                ),
                (
                    "2.2 Invoicing and Payment Terms",
                    [
                        "The Supplier shall invoice monthly in arrears. The Client shall pay "
                        "each correctly rendered invoice within thirty (30) days of the invoice "
                        "date. Payment shall be made in pounds sterling by bank transfer.",
                        "The Client may withhold payment of any amount it disputes in good "
                        "faith provided it notifies the Supplier of the grounds within fifteen "
                        "days of the invoice date and pays the undisputed balance when due.",
                    ],
                ),
                (
                    "2.3 Late Payment Interest",
                    [
                        "Overdue amounts bear interest at one and one half (1.5) per cent per "
                        "month, compounded monthly, from the due date until payment. The "
                        "Supplier may suspend the services on ten working days written notice "
                        "if an undisputed invoice remains unpaid for more than forty-five days.",
                    ],
                ),
                (
                    "2.4 Expenses",
                    [
                        "The Client shall reimburse reasonable travel and accommodation expenses "
                        "incurred at the Client's request, provided they are pre-approved in "
                        "writing and supported by receipts. Travel time is not chargeable.",
                    ],
                ),
            ],
        ),
        Section(
            heading="ARTICLE 3 - SERVICE LEVELS",
            clauses=[
                (
                    "3.1 Availability Commitment",
                    [
                        "The Supplier shall ensure the production platform is available not less "
                        "than 99.5 per cent of the time in each calendar month, measured "
                        "excluding scheduled maintenance notified at least five working days in "
                        "advance and carried out between 22:00 and 04:00 on a Saturday or "
                        "Sunday.",
                    ],
                ),
                (
                    "3.2 Incident Response",
                    [
                        "The Supplier shall acknowledge a Priority 1 incident, meaning a "
                        "complete loss of production service, within thirty minutes and shall "
                        "work continuously to restore service. Priority 2 incidents, meaning a "
                        "material degradation affecting more than one user, shall be "
                        "acknowledged within two hours during business hours.",
                        "Business hours are 08:00 to 18:00 on working days in England. "
                        "Priority 1 cover is provided twenty-four hours a day, every day.",
                    ],
                ),
                (
                    "3.3 Service Credits",
                    [
                        "If monthly availability falls below 99.5 per cent, the Client is "
                        "entitled to a service credit of five per cent of that month's support "
                        "retainer for each full 0.5 percentage point below the commitment, up "
                        "to a maximum of thirty per cent of that month's retainer.",
                        "Service credits are the Client's sole financial remedy for failure to "
                        "meet the availability commitment, save that three consecutive months "
                        "below 99.0 per cent is a material breach entitling the Client to "
                        "terminate under clause 6.3.",
                    ],
                ),
            ],
        ),
        Section(
            heading="ARTICLE 4 - INTELLECTUAL PROPERTY",
            clauses=[
                (
                    "4.1 Client Materials and Deliverables",
                    [
                        "The Client retains all intellectual property rights in its data and in "
                        "materials it supplies. On payment in full for the relevant SOW, the "
                        "Supplier assigns to the Client all intellectual property rights in the "
                        "bespoke deliverables created specifically for the Client under that "
                        "SOW.",
                    ],
                ),
                (
                    "4.2 Supplier Background IP",
                    [
                        "The Supplier retains ownership of its pre-existing tools, libraries, "
                        "and methodologies, including its Norwood Pipeline Toolkit, and grants "
                        "the Client a perpetual, non-exclusive, non-transferable licence to use "
                        "them to the extent embedded in the deliverables and for the Client's "
                        "internal business purposes.",
                    ],
                ),
                (
                    "4.3 Third Party and Open Source Components",
                    [
                        "The Supplier shall not incorporate any component licensed under a "
                        "copyleft licence that would require the Client to disclose its own "
                        "source code, without the Client's prior written consent, and shall "
                        "maintain a written inventory of third party components used in the "
                        "deliverables.",
                    ],
                ),
            ],
        ),
        Section(
            heading="ARTICLE 5 - CONFIDENTIALITY AND DATA PROTECTION",
            clauses=[
                (
                    "5.1 Confidentiality",
                    [
                        "Each party shall keep confidential all non-public information "
                        "disclosed by the other and shall use it only to perform this "
                        "Agreement. This obligation continues for five years after termination, "
                        "and indefinitely in respect of information that constitutes a trade "
                        "secret.",
                    ],
                ),
                (
                    "5.2 Data Protection",
                    [
                        "In relation to personal data processed under this Agreement the Client "
                        "is the controller and the Supplier is the processor. The Supplier "
                        "shall process personal data only on the Client's documented "
                        "instructions, shall impose equivalent obligations on any "
                        "sub-processor, and shall notify the Client without undue delay and in "
                        "any event within twenty-four hours of becoming aware of a personal "
                        "data breach.",
                        "The Supplier shall not transfer personal data outside the United "
                        "Kingdom without the Client's prior written consent and an appropriate "
                        "transfer mechanism.",
                    ],
                ),
            ],
        ),
        Section(
            heading="ARTICLE 6 - TERM AND TERMINATION",
            clauses=[
                (
                    "6.1 Term",
                    [
                        "This Agreement begins on 3 September 2024 and continues for an initial "
                        "period of twenty-four months, after which it renews automatically for "
                        "successive twelve-month periods unless terminated in accordance with "
                        "this Article 6.",
                    ],
                ),
                (
                    "6.2 Termination for Convenience",
                    [
                        "Either party may terminate this Agreement or any SOW for convenience by "
                        "giving thirty (30) days written notice, save that the Client shall pay "
                        "for all services performed and all non-cancellable commitments "
                        "properly incurred up to the termination date.",
                    ],
                ),
                (
                    "6.3 Termination for Cause",
                    [
                        "Either party may terminate immediately by written notice if the other "
                        "commits a material breach and fails to remedy it within fourteen (14) "
                        "days of written notice specifying the breach, or if the other becomes "
                        "insolvent, enters administration, or has a receiver appointed over any "
                        "of its assets.",
                    ],
                ),
                (
                    "6.4 Exit Assistance",
                    [
                        "For sixty days after termination the Supplier shall, at the Client's "
                        "request and at the daily rate in clause 2.1, provide reasonable "
                        "assistance to transfer the services to the Client or a replacement "
                        "supplier, and shall return or securely delete the Client's data as the "
                        "Client directs.",
                    ],
                ),
            ],
        ),
        Section(
            heading="ARTICLE 7 - LIABILITY",
            clauses=[
                (
                    "7.1 Limitation of Liability",
                    [
                        "Subject to clause 7.2, each party's total aggregate liability arising "
                        "out of or in connection with this Agreement, whether in contract, tort "
                        "including negligence, or otherwise, is limited to the greater of two "
                        "hundred and fifty thousand pounds (250,000) and the total fees paid or "
                        "payable by the Client in the twelve months immediately preceding the "
                        "event giving rise to the claim.",
                        "Neither party is liable for loss of profit, loss of revenue, loss of "
                        "anticipated savings, or any indirect or consequential loss, whether or "
                        "not it was foreseeable.",
                    ],
                ),
                (
                    "7.2 Excluded Liabilities",
                    [
                        "Nothing in this Agreement limits or excludes liability for death or "
                        "personal injury caused by negligence, for fraud or fraudulent "
                        "misrepresentation, for the Client's obligation to pay fees properly "
                        "due, for either party's breach of clause 5.1, or for any liability "
                        "that cannot lawfully be limited.",
                    ],
                ),
                (
                    "7.3 Insurance",
                    [
                        "The Supplier shall maintain professional indemnity insurance of not "
                        "less than two million pounds (2,000,000) per claim and cyber liability "
                        "insurance of not less than one million pounds (1,000,000) for the term "
                        "of this Agreement and for six years afterwards.",
                    ],
                ),
            ],
        ),
        Section(
            heading="ARTICLE 8 - GENERAL",
            clauses=[
                (
                    "8.1 Governing Law",
                    [
                        "This Agreement is governed by the law of England and Wales and the "
                        "parties submit to the exclusive jurisdiction of the courts of England "
                        "and Wales.",
                    ],
                ),
                (
                    "8.2 Dispute Resolution",
                    [
                        "Before commencing proceedings the parties shall escalate the dispute to "
                        "a director of each party, who shall meet within ten working days. If "
                        "the dispute is unresolved twenty working days after that meeting "
                        "either party may commence proceedings. This clause does not prevent "
                        "an application for injunctive relief.",
                    ],
                ),
                (
                    "8.3 Assignment and Subcontracting",
                    [
                        "Neither party may assign this Agreement without the other's prior "
                        "written consent, except to a successor of its whole business. The "
                        "Supplier may subcontract with the Client's prior written consent.",
                    ],
                ),
                (
                    "8.4 Force Majeure",
                    [
                        "Neither party is liable for failure to perform caused by an event "
                        "beyond its reasonable control, provided it notifies the other promptly "
                        "and mitigates the effect. If the event continues for more than sixty "
                        "days either party may terminate on fifteen days written notice.",
                    ],
                ),
            ],
        ),
    ],
)


VANTAGE_NDA = Contract(
    filename="Mutual_NDA_Vantage_Whitcombe.pdf",
    title="MUTUAL NON-DISCLOSURE AGREEMENT",
    subtitle="Evaluation of a proposed minority investment",
    parties=[
        "THIS AGREEMENT is dated 18 January 2025 and is made between VANTAGE "
        "ROBOTICS LIMITED, registered in England and Wales under number 12904455, "
        "whose registered office is at Unit 9, Sheffield Technology Park, Cooper "
        "Buildings, Sheffield S1 2NS (\"Vantage\"), and WHITCOMBE CAPITAL LLP, a "
        "limited liability partnership registered under number OC418872, whose "
        "registered office is at 22 St James's Square, London SW1Y 4JH "
        "(\"Whitcombe\").",
        "The parties wish to exchange information for the sole purpose of "
        "evaluating a proposed minority equity investment by Whitcombe in Vantage "
        "(the \"Permitted Purpose\").",
    ],
    sections=[
        Section(
            heading="1. CONFIDENTIAL INFORMATION",
            clauses=[
                (
                    "1.1 Definition",
                    [
                        "\"Confidential Information\" means all information disclosed by or on "
                        "behalf of one party (the \"Discloser\") to the other (the "
                        "\"Recipient\"), in any form and whether or not marked as confidential, "
                        "including financial statements, forecasts, customer and supplier "
                        "lists, pricing, technical designs, source code, manufacturing "
                        "processes, employee information, and the existence and contents of "
                        "the discussions between the parties.",
                    ],
                ),
                (
                    "1.2 Exclusions",
                    [
                        "Confidential Information does not include information that is or "
                        "becomes public other than through breach of this Agreement, that the "
                        "Recipient already lawfully held free of any duty of confidence, that "
                        "the Recipient independently develops without use of the Discloser's "
                        "information, or that a third party lawfully discloses to the "
                        "Recipient without restriction.",
                        "The party asserting an exclusion bears the burden of proving it by "
                        "contemporaneous written records.",
                    ],
                ),
            ],
        ),
        Section(
            heading="2. OBLIGATIONS OF THE RECIPIENT",
            clauses=[
                (
                    "2.1 Use and Non-Disclosure",
                    [
                        "The Recipient shall use the Confidential Information solely for the "
                        "Permitted Purpose, shall keep it confidential, and shall protect it "
                        "with no less care than it applies to its own confidential information "
                        "of similar importance and in any event with reasonable care.",
                    ],
                ),
                (
                    "2.2 Permitted Recipients",
                    [
                        "The Recipient may disclose Confidential Information only to those of "
                        "its directors, employees, and professional advisers who need to know "
                        "it for the Permitted Purpose and who are bound by obligations of "
                        "confidentiality at least as protective as this Agreement. The "
                        "Recipient remains liable for any breach by such persons.",
                        "Whitcombe may additionally disclose to its limited partners on a "
                        "no-names basis, and to a prospective co-investor only with Vantage's "
                        "prior written consent.",
                    ],
                ),
                (
                    "2.3 Compelled Disclosure",
                    [
                        "If the Recipient is required by law, regulation, or a competent "
                        "authority to disclose Confidential Information, it may do so provided "
                        "it gives the Discloser as much prior notice as is lawful and "
                        "practicable, discloses only the minimum required, and uses reasonable "
                        "efforts to obtain confidential treatment.",
                    ],
                ),
                (
                    "2.4 No Reverse Engineering",
                    [
                        "The Recipient shall not analyse, disassemble, or reverse engineer any "
                        "sample, prototype, or software provided to it, nor permit any third "
                        "party to do so.",
                    ],
                ),
            ],
        ),
        Section(
            heading="3. TERM AND RETURN OF INFORMATION",
            clauses=[
                (
                    "3.1 Duration of Obligations",
                    [
                        "The obligations in this Agreement take effect on the date of this "
                        "Agreement and continue for three (3) years from that date, except "
                        "that obligations in respect of information constituting a trade secret "
                        "continue for as long as that information remains a trade secret.",
                        "This Agreement terminates automatically on completion of any "
                        "investment agreement between the parties that contains equivalent "
                        "confidentiality provisions.",
                    ],
                ),
                (
                    "3.2 Return and Destruction",
                    [
                        "On the Discloser's written request the Recipient shall, within ten (10) "
                        "business days, return or irretrievably destroy all Confidential "
                        "Information and all copies, and shall confirm in writing signed by an "
                        "authorised officer that it has done so.",
                        "The Recipient may retain one copy to the extent required by law or its "
                        "internal compliance policies, and any copy held in routine electronic "
                        "backups, provided it remains subject to this Agreement for as long as "
                        "it is retained.",
                    ],
                ),
            ],
        ),
        Section(
            heading="4. NO LICENCE, NO WARRANTY, NO OBLIGATION",
            clauses=[
                (
                    "4.1 No Licence",
                    [
                        "No licence of any intellectual property right is granted by this "
                        "Agreement. All Confidential Information remains the property of the "
                        "Discloser.",
                    ],
                ),
                (
                    "4.2 No Warranty",
                    [
                        "Confidential Information is provided as is. Neither party warrants its "
                        "accuracy or completeness, and neither party is liable to the other for "
                        "any reliance placed on it, save in the case of fraud.",
                    ],
                ),
                (
                    "4.3 No Obligation to Proceed",
                    [
                        "Nothing in this Agreement obliges either party to proceed with the "
                        "proposed investment or with any further discussion, and either party "
                        "may terminate the discussions at any time without liability.",
                    ],
                ),
            ],
        ),
        Section(
            heading="5. NON-SOLICITATION",
            clauses=[
                (
                    "5.1 Employees",
                    [
                        "For twelve (12) months from the date of this Agreement Whitcombe shall "
                        "not solicit for employment any employee of Vantage with whom it comes "
                        "into contact as a result of the Permitted Purpose. A general "
                        "advertisement not specifically targeted at such employees, and any "
                        "response to it, is not a breach of this clause.",
                    ],
                ),
            ],
        ),
        Section(
            heading="6. REMEDIES AND GENERAL",
            clauses=[
                (
                    "6.1 Injunctive Relief",
                    [
                        "The parties agree that damages alone may be an inadequate remedy for "
                        "breach of this Agreement and that the Discloser is entitled to seek "
                        "injunctive relief or specific performance without the need to prove "
                        "special damage or provide security.",
                    ],
                ),
                (
                    "6.2 Governing Law and Jurisdiction",
                    [
                        "This Agreement is governed by the law of England and Wales and the "
                        "parties submit to the exclusive jurisdiction of the courts of England "
                        "and Wales.",
                    ],
                ),
                (
                    "6.3 Entire Agreement and Variation",
                    [
                        "This Agreement is the entire agreement between the parties in relation "
                        "to its subject matter and may be varied only in writing signed by both "
                        "parties. No failure to exercise a right operates as a waiver of it.",
                    ],
                ),
            ],
        ),
    ],
)


OKONJO_EMPLOYMENT = Contract(
    filename="Employment_Agreement_R_Okonjo.pdf",
    title="CONTRACT OF EMPLOYMENT",
    subtitle="Senior Research Scientist",
    parties=[
        "THIS CONTRACT is made on 6 May 2024 between FERNDALE BIOSCIENCE LIMITED, "
        "registered in England and Wales under number 07713942, whose registered "
        "office is at Ferndale House, Granta Park, Cambridge CB21 6GP (the "
        "\"Company\"), and RACHEL OKONJO of 14 Priory Gardens, Cambridge CB4 3HN "
        "(the \"Employee\").",
        "This document sets out the terms of the Employee's employment and "
        "constitutes the written statement of particulars required by section 1 of "
        "the Employment Rights Act 1996.",
    ],
    sections=[
        Section(
            heading="1. APPOINTMENT AND DUTIES",
            clauses=[
                (
                    "1.1 Position",
                    [
                        "The Company employs the Employee as Senior Research Scientist, "
                        "reporting to the Head of Molecular Discovery. The Employee shall "
                        "devote her full working time and attention to the business of the "
                        "Company and shall perform such duties as are reasonably assigned to "
                        "her consistent with that position.",
                    ],
                ),
                (
                    "1.2 Place of Work",
                    [
                        "The Employee's normal place of work is Ferndale House, Granta Park, "
                        "Cambridge. The Company may require the Employee to work at any other "
                        "site within twenty-five miles of that address, and the Employee may "
                        "work remotely up to two days each week with her manager's agreement.",
                    ],
                ),
                (
                    "1.3 Outside Interests",
                    [
                        "The Employee shall not, without the Company's prior written consent, "
                        "engage in any other business or accept any appointment that competes "
                        "with the Company or interferes with the performance of her duties. "
                        "Holding shares amounting to less than three per cent of a listed "
                        "company is not a breach of this clause.",
                    ],
                ),
            ],
        ),
        Section(
            heading="2. COMMENCEMENT AND PROBATION",
            clauses=[
                (
                    "2.1 Start Date and Continuous Service",
                    [
                        "Employment begins on 3 June 2024. No employment with a previous "
                        "employer counts towards the Employee's period of continuous "
                        "employment.",
                    ],
                ),
                (
                    "2.2 Probationary Period",
                    [
                        "The first six (6) months of employment are probationary. The Company "
                        "may extend the probationary period by up to three months on written "
                        "notice given before it expires. During the probationary period either "
                        "party may terminate the employment on one (1) week written notice.",
                    ],
                ),
            ],
        ),
        Section(
            heading="3. REMUNERATION AND BENEFITS",
            clauses=[
                (
                    "3.1 Salary",
                    [
                        "The Employee's initial gross annual salary is SIXTY-EIGHT THOUSAND "
                        "FIVE HUNDRED POUNDS (68,500) payable in twelve equal monthly "
                        "instalments in arrears on the twenty-fifth day of each month by credit "
                        "transfer, subject to deduction of income tax and national insurance.",
                        "Salary is reviewed annually each April. A review does not guarantee an "
                        "increase, and the Company may not reduce the salary without the "
                        "Employee's written consent.",
                    ],
                ),
                (
                    "3.2 Annual Bonus",
                    [
                        "The Employee is eligible for a discretionary annual bonus of up to "
                        "fifteen (15) per cent of base salary, determined by reference to "
                        "individual objectives agreed at the start of each financial year and "
                        "to the Company's performance.",
                        "Any bonus is paid in the March following the financial year to which "
                        "it relates and is not payable if the Employee has resigned or been "
                        "given notice of dismissal for cause on or before the payment date.",
                    ],
                ),
                (
                    "3.3 Pension",
                    [
                        "The Company shall enrol the Employee in its group personal pension "
                        "scheme and shall contribute an amount equal to seven per cent of base "
                        "salary provided the Employee contributes at least four per cent.",
                    ],
                ),
                (
                    "3.4 Other Benefits",
                    [
                        "The Employee is entitled to private medical insurance for herself and "
                        "her dependants, life assurance of four times base salary, and a "
                        "professional subscription allowance of five hundred pounds each year. "
                        "Benefits are provided under policies the Company may vary or withdraw "
                        "on three months notice.",
                    ],
                ),
            ],
        ),
        Section(
            heading="4. HOURS, HOLIDAY, AND ABSENCE",
            clauses=[
                (
                    "4.1 Working Hours",
                    [
                        "Normal working hours are 09:00 to 17:30 on Monday to Friday with one "
                        "hour for lunch, amounting to 37.5 hours each week. The Employee shall "
                        "work such additional hours as are reasonably necessary for the proper "
                        "performance of her duties without further payment.",
                    ],
                ),
                (
                    "4.2 Holiday Entitlement",
                    [
                        "The Employee is entitled to twenty-eight (28) days paid holiday in each "
                        "holiday year in addition to public holidays in England. The holiday "
                        "year runs from 1 January to 31 December, and entitlement accrues "
                        "pro rata in the year of joining or leaving.",
                        "Up to five days of unused entitlement may be carried into the "
                        "following holiday year and must be taken by 31 March. On termination "
                        "the Employee is paid for accrued untaken holiday, and the Company may "
                        "deduct pay for holiday taken in excess of entitlement.",
                    ],
                ),
                (
                    "4.3 Sickness Absence",
                    [
                        "Subject to notifying her manager by 09:30 on the first day of absence "
                        "and providing a fit note for absence exceeding seven consecutive days, "
                        "the Employee is entitled to full pay for up to thirteen weeks of "
                        "certified sickness absence in any rolling twelve-month period, "
                        "inclusive of statutory sick pay, and thereafter to statutory sick pay "
                        "alone.",
                    ],
                ),
            ],
        ),
        Section(
            heading="5. TERMINATION OF EMPLOYMENT",
            clauses=[
                (
                    "5.1 Notice Period",
                    [
                        "After the probationary period either party may terminate the employment "
                        "by giving three (3) months written notice. The Company may give longer "
                        "notice if required by section 86 of the Employment Rights Act 1996.",
                    ],
                ),
                (
                    "5.2 Payment in Lieu and Garden Leave",
                    [
                        "The Company may terminate the employment immediately and pay in lieu of "
                        "notice a sum equal to base salary only for the unexpired notice "
                        "period, payable in instalments and subject to mitigation. During any "
                        "notice period the Company may require the Employee to take garden "
                        "leave, during which she remains bound by all terms of this contract.",
                    ],
                ),
                (
                    "5.3 Summary Dismissal",
                    [
                        "The Company may terminate the employment without notice or payment in "
                        "lieu if the Employee commits an act of gross misconduct, is convicted "
                        "of an offence rendering her unsuitable for her duties, commits a "
                        "serious or repeated breach of this contract, or is disqualified from "
                        "acting as a director.",
                    ],
                ),
                (
                    "5.4 Return of Property",
                    [
                        "On termination the Employee shall return all Company property, "
                        "including laptops, access cards, laboratory notebooks, samples, and "
                        "all documents and copies containing confidential information, and "
                        "shall irretrievably delete Company information from any personal "
                        "device.",
                    ],
                ),
            ],
        ),
        Section(
            heading="6. CONFIDENTIALITY AND INTELLECTUAL PROPERTY",
            clauses=[
                (
                    "6.1 Confidentiality",
                    [
                        "The Employee shall not at any time during or after her employment use "
                        "or disclose any confidential information of the Company, including "
                        "research data, assay protocols, candidate compound structures, "
                        "regulatory strategy, and commercial terms with partners, except in the "
                        "proper performance of her duties or as required by law.",
                        "Nothing in this contract prevents the Employee from making a protected "
                        "disclosure under the Public Interest Disclosure Act 1998 or reporting "
                        "a matter to a regulator.",
                    ],
                ),
                (
                    "6.2 Inventions and Intellectual Property",
                    [
                        "All inventions, designs, and works created by the Employee in the "
                        "course of her employment belong to the Company, subject to sections 39 "
                        "to 43 of the Patents Act 1977. The Employee shall promptly disclose "
                        "them, shall execute any document required to vest the rights in the "
                        "Company, and waives her moral rights in them.",
                    ],
                ),
            ],
        ),
        Section(
            heading="7. POST-TERMINATION RESTRICTIONS",
            clauses=[
                (
                    "7.1 Non-Competition",
                    [
                        "For six (6) months after the termination date the Employee shall not be "
                        "engaged in any business that competes with any part of the Company's "
                        "business in which she was materially involved in the twelve months "
                        "before termination, within the United Kingdom.",
                    ],
                ),
                (
                    "7.2 Non-Solicitation and Non-Dealing",
                    [
                        "For twelve (12) months after the termination date the Employee shall "
                        "not solicit or seek to entice away any person who was an employee of "
                        "the Company at senior scientist level or above with whom she worked in "
                        "her final twelve months, nor solicit or deal with any research "
                        "partner, licensee, or supplier with whom she had material dealings in "
                        "that period.",
                    ],
                ),
                (
                    "7.3 Reasonableness and Reduction",
                    [
                        "The restrictions in this clause 7 are reduced by any period the Employee "
                        "spends on garden leave. The parties consider the restrictions "
                        "reasonable and necessary to protect the Company's legitimate business "
                        "interests, and if any is held unenforceable it shall apply with the "
                        "minimum modification necessary to make it enforceable.",
                    ],
                ),
            ],
        ),
        Section(
            heading="8. GENERAL",
            clauses=[
                (
                    "8.1 Disciplinary and Grievance Procedures",
                    [
                        "The Company's disciplinary and grievance procedures are set out in the "
                        "staff handbook and do not form part of this contract. There is no "
                        "collective agreement affecting this employment.",
                    ],
                ),
                (
                    "8.2 Governing Law",
                    [
                        "This contract is governed by the law of England and Wales and the "
                        "parties submit to the exclusive jurisdiction of the courts of England "
                        "and Wales.",
                    ],
                ),
                (
                    "8.3 Entire Agreement",
                    [
                        "This contract supersedes all previous agreements and offer letters "
                        "relating to the Employee's employment.",
                    ],
                ),
            ],
        ),
    ],
)


CORPUS: list[Contract] = [
    HENDERSON_LEASE,
    BRIGHTLINE_MSA,
    VANTAGE_NDA,
    OKONJO_EMPLOYMENT,
]
