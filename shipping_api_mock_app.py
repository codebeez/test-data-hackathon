from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import random
import uvicorn
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Mock Shipping API",
    description="A simple mock service to simulate external shipping cost estimation.",
    version="1.0.0"
)

class ShippingEstimateRequest(BaseModel):
    product_id: int
    destination_zip_code: str = Field(..., pattern=r"^\d{5}(-\d{4})?$")
    weight_kg: float = Field(..., gt=0)
    distance_km: float = Field(..., gt=0)

class ShippingEstimateResponse(BaseModel):
    product_id: int
    destination_zip_code: str
    estimated_cost: float
    estimated_delivery_days: int
    carrier: str

@app.post("/estimate", response_model=ShippingEstimateResponse)
async def estimate_shipping(request: ShippingEstimateRequest):
    """
    Provides a mock shipping estimate.
    """
    logger.info(f"Mock Shipping API received request: {request.model_dump_json()}")

    # Simulate some processing delay
    # await asyncio.sleep(random.uniform(0.1, 0.5))

    # Simulate occasional errors (e.g., 10% chance)
    if random.random() < 0.05: # 5% chance of internal server error
        logger.error("Mock Shipping API: Simulating an internal server error.")
        raise HTTPException(status_code=500, detail="Simulated internal shipping service error")

    if request.destination_zip_code == "00000": # Specific zip for testing "service unavailable"
        logger.warning(f"Mock Shipping API: Simulating service unavailable for ZIP {request.destination_zip_code}")
        raise HTTPException(status_code=404, detail=f"Shipping service not available for ZIP code {request.destination_zip_code}")


    base_cost = 5.0
    cost_per_kg = random.uniform(1.5, 3.0)
    cost_per_100km = random.uniform(0.8, 1.5)

    estimated_cost = base_cost + (request.weight_kg * cost_per_kg) + (request.distance_km * cost_per_100km / 100)
    estimated_delivery_days = max(1, int(request.distance_km / random.randint(400, 600)) + int(request.weight_kg / 10) + random.randint(0,2))
    
    carriers = ["ShipFast", "QuickHaul", "EcoDeliver", "PonyExpressMock"]
    carrier = random.choice(carriers)

    response_data = ShippingEstimateResponse(
        product_id=request.product_id,
        destination_zip_code=request.destination_zip_code,
        estimated_cost=round(estimated_cost, 2),
        estimated_delivery_days=estimated_delivery_days,
        carrier=carrier
    )
    logger.info(f"Mock Shipping API responding with: {response_data.model_dump_json()}")
    return response_data

@app.get("/health", status_code=200)
async def health_check():
    return {"status": "healthy", "service": "Mock Shipping API"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)