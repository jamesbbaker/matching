import stripe
from config import payment

class Stripe(object):

    def __init__(self):
        # set connection
        stripe.api_key = payment.PROCESSORS['stripe']['secret']
        self.secret = payment.PROCESSORS['stripe']['secret']
        self.currency = payment.PROCESSORS['stripe']['currency']
        self.processor = stripe

    def charge(self, token, amount, description):
        return self.processor.Charge.create(
            amount=amount,
            currency=self.currency,
            source=token,  # obtained with Stripe.js
            description=description
        )

    def customer(self, token, description):
        return self.processor.Customer.create(
            description=description,
            source=token  # obtained with Stripe.js
        )
    
    def subscribe(self, subscription, plan, stripe_id):
        ## add users subscription
        return stripe.Subscription.create(
            customer=stripe_id,
            items=[
                {
                    "plan": plan,
                },
            ]
        )

    def getSubscription(self, subscription_id):
        return self.processor.Subscription.retrieve(subscription_id)

    def cancel(self, token):
        sub = stripe.Subscription.retrieve("sub_BNHfxLN6g7Rdh3")
        return sub.delete()

    def getCustomer(self, stripe_id):
        customer = stripe.Customer.retrieve(stripe_id)
        if 'deleted' in customer:
            return False

        return customer

    def swapPlan(self, new_plan, subscription_id, prorate=True):
        subscription = stripe.Subscription.retrieve(subscription_id)
        item_id = subscription['items']['data'][0].id
        return stripe.Subscription.modify(
            subscription_id,
            items=[{
                "id": item_id,
                "plan": new_plan,
            }],
            prorate = prorate
        )
