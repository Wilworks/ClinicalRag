# api/guidelines_data.py
# Contains official protocols from the Ghana Standard Treatment Guidelines (2018)
# and drug status mappings from the National Health Insurance Scheme (NHIS) Medicines List.

GHANA_GUIDELINES = {
    "malaria": {
        "title": "Ghana Standard Treatment Guidelines (2018) - Malaria",
        "guideline": (
            "Uncomplicated malaria: First-line treatment is Artemether-Lumefantrine (AL) or Artesunate-Amodiaquine (AA). "
            "In pregnancy: For uncomplicated P. falciparum in the first trimester, Oral Quinine is recommended. "
            "In the second and third trimesters, AL or AA is the standard first-line treatment. "
            "Severe malaria: Intravenous Artesunate is the preferred first-line therapy for adults and children, "
            "followed by a full oral course of ACT when the patient can tolerate oral medications. If IV Artesunate is unavailable, "
            "IV Artemether or IM Quinine are recommended alternatives."
        ),
        "drugs": [
            {"name": "Artemether-Lumefantrine (AL)", "nhis": "Covered", "status": "Widely available at CHPS, health centers, and hospitals"},
            {"name": "Artesunate-Amodiaquine (AA)", "nhis": "Covered", "status": "Available in public pharmacies"},
            {"name": "Oral Quinine", "nhis": "Covered", "status": "Pregnancy standard, available in district hospitals"},
            {"name": "Intravenous Artesunate", "nhis": "Covered", "status": "Requires district or regional hospital stock"}
        ]
    },
    "sickle cell": {
        "title": "Ghana Standard Treatment Guidelines (2018) - Sickle Cell Disease",
        "guideline": (
            "Maintenance: Daily oral Folic Acid (5mg). "
            "Hydroxyurea therapy is recommended for patients with frequent painful crises (3 or more per year), "
            "history of acute chest syndrome, or severe chronic anemia. Starting dose is 15 mg/kg/day, "
            "escalated based on blood counts to a maximum of 30 mg/kg/day. "
            "Prophylaxis: Daily Penicillin V (125mg for infants under 3 years, 250mg for 3-5 years) to prevent pneumococcal sepsis. "
            "Crisis management: Hydration (oral or IV), adequate analgesia (paracetamol/ibuprofen for mild, tramadol/morphine for severe), "
            "and immediate broad-spectrum antibiotics if fever is present."
        ),
        "drugs": [
            {"name": "Hydroxyurea", "nhis": "Covered", "status": "Available in regional hospitals and specialized clinics"},
            {"name": "Folic Acid", "nhis": "Covered", "status": "Widely available at all healthcare levels"},
            {"name": "Penicillin V", "nhis": "Covered", "status": "Available in public pharmacies"},
            {"name": "Morphine", "nhis": "Covered", "status": "Requires prescription, stock in larger facilities"}
        ]
    },
    "eclampsia": {
        "title": "Ghana Standard Treatment Guidelines (2018) - Pre-Eclampsia & Eclampsia",
        "guideline": (
            "Severe Pre-Eclampsia / Eclampsia management: Magnesium Sulfate (MgSO4) is the drug of choice to prevent and treat seizures. "
            "Loading dose: 4g IV (as a 20% solution over 5-10 mins) + 10g IM (5g in each buttock as a 50% solution with 1ml of 1% lidocaine). "
            "Maintenance dose: 5g IM in alternating buttocks every 4 hours for 24 hours after delivery or after the last fit, "
            "only if respiratory rate >= 16/min, patellar reflex is present, and urine output is >= 100ml in 4 hours. "
            "Antidote: 10ml of Calcium Gluconate (10% solution) IV slowly over 10 mins if toxicity (respiratory depression, absent reflexes) occurs. "
            "Antihypertensives: Hydralazine 5mg slow IV every 15-20 mins (max 20mg) or Labetalol 20mg IV if diastolic BP >= 110 mmHg."
        ),
        "drugs": [
            {"name": "Magnesium Sulfate (MgSO4)", "nhis": "Covered", "status": "Critical maternal standard; stocked in labor wards"},
            {"name": "Calcium Gluconate", "nhis": "Covered", "status": "Antidote; kept in emergency trays"},
            {"name": "Hydralazine", "nhis": "Covered", "status": "Available in emergency labor stocks"},
            {"name": "Labetalol", "nhis": "Covered", "status": "Common hospital alternative"}
        ]
    },
    "tuberculosis": {
        "title": "Ghana National Tuberculosis Control Program Guidelines",
        "guideline": (
            "Treatment regimen for new cases: 2 months of intensive phase with Rifampicin (R), Isoniazid (H), Pyrazinamide (Z), and Ethambutol (E) [2HRZE], "
            "followed by 4 months of continuation phase with Rifampicin and Isoniazid [4HR]. "
            "Fixed-dose combinations (FDCs) are highly preferred to improve adherence. "
            "All tuberculosis treatments in Ghana are strictly under directly observed therapy (DOTS) protocol."
        ),
        "drugs": [
            {"name": "Rifampicin/Isoniazid/Pyrazinamide/Ethambutol (HRZE)", "nhis": "Free Program", "status": "Available exclusively at designated TB DOTS clinics at no cost"},
            {"name": "Rifampicin/Isoniazid (HR)", "nhis": "Free Program", "status": "Designated public health facilities under DOTS"}
        ]
    },
    "diabetes": {
        "title": "Ghana Standard Treatment Guidelines (2018) - Type 2 Diabetes",
        "guideline": (
            "First-line oral monotherapy: Metformin (starting 500mg daily, increased to max 2g/day) unless contraindicated (renal impairment). "
            "Second-line combination: Metformin + Sulfonylurea (e.g. Glibenclamide or Gliclazide). "
            "Third-line: Metformin + Insulin (neutral protamine Hagedorn / NPH insulin) if glycemic control remains poor (HbA1c > 7.5% or fasting blood glucose > 7.0 mmol/L). "
            "Lifestyle modification (diet, exercise, weight loss) is critical at all stages."
        ),
        "drugs": [
            {"name": "Metformin", "nhis": "Covered", "status": "First-line monotherapy, widely available at all tiers"},
            {"name": "Glibenclamide", "nhis": "Covered", "status": "Available in most public pharmacies"},
            {"name": "Gliclazide", "nhis": "Covered", "status": "Available in district/regional pharmacies"},
            {"name": "NPH Insulin", "nhis": "Covered", "status": "Requires cold-chain storage, stocked in hospitals"}
        ]
    }
}
